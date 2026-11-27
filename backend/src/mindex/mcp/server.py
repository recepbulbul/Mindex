"""The MCP server (F9): `get_market_data`, `get_portfolio`, `place_order` over streamable HTTP.

Look-ahead: the tools read the market only through `ArenaSession.view` (a `MarketView` of
the current day) and answer in the form LLM agents see: anonymous asset codes, a day
number instead of a date, returns instead of price levels (docs/04-ai-pipeline.md).

Authorisation (NF3): every request needs an agent token (`mindex.mcp.auth`); the caller is
the agent that token names. A call that names another agent's portfolio is refused.
"""

from typing import Any

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import AnyHttpUrl, BaseModel, ValidationError

from mindex.agents.llm import anonymise, asset_features
from mindex.config import Settings
from mindex.domain.decision import Decision
from mindex.mcp.auth import AgentTokenVerifier
from mindex.mcp.session import ArenaSession, SessionFinishedError

INSTRUCTIONS = (
    "Mindex arenası. Her gün: get_market_data ile günü oku, get_portfolio ile portföyüne bak, "
    "place_order ile hedef ağırlıklarını ver. Emir bir sonraki günün açılışında gerçekleşir; "
    "oturumdaki bütün ajanlar emir verince gün ilerler."
)


class OrderLine(BaseModel):
    asset: str  # anonymous code from get_market_data, e.g. ASSET_A
    weight: float


def caller_of(agent_id: str | None) -> str:
    """The authenticated agent; refuses a call aimed at any other agent's portfolio."""
    token = get_access_token()
    if token is None:
        raise ToolError("Kimlik doğrulanmadı: ajan token'ı gerekli.")
    if agent_id is not None and agent_id != token.client_id:
        raise ToolError("Yetkisiz (403): token yalnızca kendi ajanının portföyüne yetkilidir.")
    return token.client_id


def build_server(session: ArenaSession, settings: Settings, *, url: str) -> MCPServer:
    """`url` is the server's public base URL (announced in the 401 challenge)."""
    server = MCPServer(
        "mindex",
        instructions=INSTRUCTIONS,
        token_verifier=AgentTokenVerifier(settings, session.agent_ids),
        # Tokens come from `mindex mcp token`, there is no OAuth flow; the SDK still wants
        # an issuer to name.
        auth=AuthSettings(issuer_url=AnyHttpUrl(url), resource_server_url=None),
    )
    codes = anonymise(session.view.assets)
    by_code = {code: asset for asset, code in codes.items()}

    # The tools are `async` so the SDK runs them on the event loop, one at a time: the
    # session needs no lock.
    @server.tool()
    async def get_market_data() -> dict[str, Any]:  # pyright: ignore[reportUnusedFunction]
        """Bugünün kapanışına kadarki piyasa: varlık başına son 30 günün getirileri ve
        göstergeler. Varlıklar anonim kodlarla (ASSET_A...), gün sıra numarasıyla verilir."""
        caller_of(None)
        view = session.view
        costs = session.costs
        return {
            "day": session.step,
            "finished": session.finished,
            "fear_greed_index": view.fear_greed,
            "trading_cost_pct": round((costs.commission_rate + costs.slippage) * 100, 3),
            "assets": {codes[a]: asset_features(view, a) for a in view.assets},
        }

    @server.tool()
    async def get_portfolio(agent_id: str | None = None) -> dict[str, Any]:  # pyright: ignore[reportUnusedFunction]
        """Çağıran ajanın portföyü, bugünün kapanış fiyatlarıyla. `agent_id` vermeyin; verilirse
        token'ın ajanı olmak zorundadır."""
        agent = caller_of(agent_id)
        view = session.view
        prices = {a: view.bar(a).close for a in view.assets}
        portfolio = session.portfolio(agent)
        weights = portfolio.weights(prices)
        return {
            "agent_id": agent,
            "day": session.step,
            "equity": round(portfolio.value(prices), 2),
            "cash": round(portfolio.cash, 2),
            "weights": {codes[a]: round(w, 4) for a, w in weights.items()},
            "cash_weight": round(1 - sum(weights.values()), 4),
        }

    @server.tool()
    async def place_order(  # pyright: ignore[reportUnusedFunction]
        allocations: list[OrderLine],
        confidence: float,
        rationale: str,
        agent_id: str | None = None,
    ) -> dict[str, Any]:
        """Çağıran ajanın hedef portföy ağırlıkları (long-only, toplam <= 1, kalan nakit).
        Bir sonraki günün açılışında komisyon ve kaymayla gerçekleşir. Aynı gün yeniden
        verilirse öncekinin yerine geçer. `confidence` 0-1, `rationale` 10-2000 karakter."""
        agent = caller_of(agent_id)
        unknown = sorted({line.asset for line in allocations} - set(by_code))
        if unknown:
            raise ToolError(f"Bilinmeyen varlık kodu: {', '.join(unknown)}.")
        try:
            decision = Decision.model_validate(
                {
                    "allocations": [
                        {"asset": by_code[line.asset], "weight": line.weight}
                        for line in allocations
                    ],
                    "confidence": confidence,
                    "rationale": rationale,
                }
            )
            advanced = session.place_order(agent, decision)
        except ValidationError as exc:
            problems = "; ".join(
                f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors(include_url=False)
            )
            raise ToolError(f"Geçersiz emir: {problems}") from None
        except SessionFinishedError:
            raise ToolError("Oturum bitti: emir verilecek gün kalmadı.") from None
        return {
            "accepted": True,
            "day": session.step,
            "day_advanced": advanced,
            "waiting_for_agents": session.waiting_for,
        }

    return server
