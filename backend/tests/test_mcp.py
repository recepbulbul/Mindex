"""MCP server (F9, NF3): the three tools, look-ahead, and per-agent authorisation."""

import asyncio
import json
import uuid
from collections.abc import Iterator
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr
from starlette.testclient import TestClient

from conftest import synthetic_frame
from mindex import cli
from mindex.agents.llm import asset_features
from mindex.api.security import InvalidTokenError, decode_token, issue_token
from mindex.config import Settings
from mindex.data.snapshot import write_snapshot
from mindex.data.splits import SPLITS, Split
from mindex.db.models import UserRole
from mindex.domain.decision import Allocation, Asset, Decision
from mindex.mcp.auth import AgentTokenVerifier, decode_agent_token, issue_agent_token
from mindex.mcp.server import build_server
from mindex.mcp.session import ArenaSession, SessionFinishedError
from mindex.sim.market import Bar, MarketData, MarketView

SETTINGS = Settings(_env_file=None, jwt_secret=SecretStr("x" * 64))  # pyright: ignore[reportCallIssue]
START = 31
URL = "http://127.0.0.1:8765"
DAY = timedelta(days=1)


def order(weights: dict[Asset, float]) -> Decision:
    return Decision(
        allocations=[Allocation(asset=a, weight=w) for a, w in weights.items()],
        confidence=0.5,
        rationale="test order for the arena",
    )


# ---------------------------------------------------------------- session


def test_order_executes_at_the_next_open_once_everyone_ordered(market: MarketData) -> None:
    session = ArenaSession(market, ["a", "b"], start=START)
    assert (session.step, session.view.t, session.waiting_for) == (0, START, 2)

    assert session.place_order("a", order({Asset.BTC: 1.0})) is False
    assert session.step == 0  # b has not ordered: the day stands still
    assert session.portfolio("a").holdings == {}

    assert session.place_order("b", order({})) is True
    assert (session.step, session.view.t, session.waiting_for) == (1, START + 1, 2)
    a, b = session.portfolio("a"), session.portfolio("b")
    assert a.holdings.keys() == {Asset.BTC}
    assert a.cash < 100  # bought at the open of START + 1, fees paid
    assert (b.cash, b.holdings) == (10_000.0, {})  # a's order never touched b


def test_a_second_order_on_the_same_day_replaces_the_first(market: MarketData) -> None:
    session = ArenaSession(market, ["a", "b"], start=START)
    session.place_order("a", order({Asset.BTC: 1.0}))
    session.place_order("a", order({Asset.ETH: 0.5}))
    session.place_order("b", order({}))
    assert session.portfolio("a").holdings.keys() == {Asset.ETH}


def test_session_ends_on_the_last_day(market: MarketData) -> None:
    session = ArenaSession(market, ["a"], start=len(market) - 2)
    assert session.place_order("a", order({})) is True
    assert session.finished
    with pytest.raises(SessionFinishedError):
        session.place_order("a", order({}))
    with pytest.raises(ValueError, match="at least one agent"):
        ArenaSession(market, [])


# ---------------------------------------------------------------- tokens


def test_agent_token_round_trip() -> None:
    token = issue_agent_token(SETTINGS, "mcp-guest", DAY)
    agent_id, expires_at = decode_agent_token(SETTINGS, token)
    assert agent_id == "mcp-guest"
    assert expires_at > 0


def test_agent_and_user_tokens_are_not_interchangeable() -> None:
    user = issue_token(SETTINGS, uuid.uuid4(), UserRole.RESEARCHER)
    with pytest.raises(InvalidTokenError):
        decode_agent_token(SETTINGS, user)
    with pytest.raises(InvalidTokenError):
        decode_token(SETTINGS, issue_agent_token(SETTINGS, "mcp-guest", DAY))


def test_expired_forged_and_malformed_tokens_are_refused() -> None:
    other = Settings(_env_file=None, jwt_secret=SecretStr("y" * 64))  # pyright: ignore[reportCallIssue]
    for bad in (
        issue_agent_token(SETTINGS, "a", -DAY),
        issue_agent_token(other, "a", DAY),
        "not-a-token",
    ):
        with pytest.raises(InvalidTokenError):
            decode_agent_token(SETTINGS, bad)


def test_verifier_only_accepts_the_sessions_agents() -> None:
    verifier = AgentTokenVerifier(SETTINGS, {"a"})
    ok = asyncio.run(verifier.verify_token(issue_agent_token(SETTINGS, "a", DAY)))
    assert ok is not None
    assert ok.client_id == "a"
    assert asyncio.run(verifier.verify_token(issue_agent_token(SETTINGS, "stranger", DAY))) is None
    assert asyncio.run(verifier.verify_token("garbage")) is None


# ---------------------------------------------------------------- server over HTTP


class Arena:
    """The MCP server over HTTP, as an external agent reaches it."""

    def __init__(self, http: TestClient, session: ArenaSession) -> None:
        self.http = http
        self.session = session

    def post(self, method: str, params: dict[str, Any], token: str | None) -> Any:
        headers = {"Accept": "application/json, text/event-stream"}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        return self.http.post("/mcp", json=body, headers=headers)

    def call(self, agent: str, tool: str, **arguments: Any) -> dict[str, Any]:
        token = issue_agent_token(SETTINGS, agent, DAY)
        response = self.post("tools/call", {"name": tool, "arguments": arguments}, token)
        assert response.status_code == 200
        result: dict[str, Any] = response.json()["result"]
        return result

    def ok(self, agent: str, tool: str, **arguments: Any) -> dict[str, Any]:
        result = self.call(agent, tool, **arguments)
        assert result["isError"] is False, result
        data: dict[str, Any] = result["structuredContent"]
        return data

    def refused(self, agent: str, tool: str, **arguments: Any) -> str:
        result = self.call(agent, tool, **arguments)
        assert result["isError"] is True, result
        text: str = result["content"][0]["text"]
        return text


def serve(market: MarketData) -> Iterator[Arena]:
    session = ArenaSession(market, ["a", "b"], start=START)
    app = build_server(session, SETTINGS, url=URL).streamable_http_app(
        json_response=True, stateless_http=True
    )
    with TestClient(app, base_url=URL) as http:
        yield Arena(http, session)


@pytest.fixture
def arena(market: MarketData) -> Iterator[Arena]:
    yield from serve(market)


ORDER: dict[str, Any] = {"confidence": 0.6, "rationale": "trend following on the leader"}


def test_exactly_the_three_tools_are_exposed(arena: Arena) -> None:
    listed = arena.post("tools/list", {}, issue_agent_token(SETTINGS, "a", DAY)).json()
    names = {t["name"] for t in listed["result"]["tools"]}
    assert names == {"get_market_data", "get_portfolio", "place_order"}


def test_requests_without_a_valid_agent_token_get_401(arena: Arena) -> None:
    call: dict[str, Any] = {"name": "get_portfolio", "arguments": {}}
    user_token = issue_token(SETTINGS, uuid.uuid4(), UserRole.RESEARCHER)
    for token in (None, "garbage", issue_agent_token(SETTINGS, "stranger", DAY), user_token):
        assert arena.post("tools/call", call, token).status_code == 401


def test_agent_cannot_read_another_agents_portfolio(arena: Arena) -> None:
    assert "403" in arena.refused("a", "get_portfolio", agent_id="b")
    own = arena.ok("a", "get_portfolio", agent_id="a")
    assert own == arena.ok("a", "get_portfolio")
    assert own["agent_id"] == "a"


def test_agent_cannot_trade_another_agents_portfolio(arena: Arena) -> None:
    line = [{"asset": "ASSET_A", "weight": 1.0}]
    assert "403" in arena.refused("a", "place_order", allocations=line, agent_id="b", **ORDER)
    assert arena.session.waiting_for == 2  # nothing was recorded for anyone

    # Each agent's order lands in its own portfolio only.
    assert arena.ok("a", "place_order", allocations=line, **ORDER) == {
        "accepted": True,
        "day": 0,
        "day_advanced": False,
        "waiting_for_agents": 1,
    }
    assert arena.ok("b", "place_order", allocations=[], **ORDER)["day_advanced"] is True
    a, b = arena.ok("a", "get_portfolio"), arena.ok("b", "get_portfolio")
    assert (a["day"], b["day"]) == (1, 1)
    assert a["weights"].keys() == {"ASSET_A"}
    assert a["weights"]["ASSET_A"] > 0.99
    assert b == {
        "agent_id": "b",
        "day": 1,
        "equity": 10_000.0,
        "cash": 10_000.0,
        "weights": {},
        "cash_weight": 1,
    }


@pytest.mark.parametrize(
    ("allocations", "extra", "message"),
    [
        ([{"asset": "ASSET_A", "weight": 1.5}], {}, "less than or equal to 1"),
        ([{"asset": "ASSET_A", "weight": -0.1}], {}, "greater than or equal to 0"),
        (
            [{"asset": "ASSET_A", "weight": 0.7}, {"asset": "ASSET_B", "weight": 0.7}],
            {},
            "no leverage",
        ),
        (
            [{"asset": "ASSET_A", "weight": 0.2}, {"asset": "ASSET_A", "weight": 0.2}],
            {},
            "at most once",
        ),
        ([{"asset": "BTC", "weight": 0.5}], {}, "Bilinmeyen varlık kodu: BTC"),
        ([{"asset": "ASSET_Z", "weight": 0.5}], {}, "Bilinmeyen varlık kodu: ASSET_Z"),
        ([], {"confidence": 1.5}, "confidence"),
        ([], {"rationale": "short"}, "rationale"),
    ],
)
def test_place_order_uses_the_simulators_decision_rules(
    arena: Arena, allocations: list[dict[str, Any]], extra: dict[str, Any], message: str
) -> None:
    text = arena.refused("a", "place_order", allocations=allocations, **{**ORDER, **extra})
    assert message in text
    assert arena.session.waiting_for == 2  # a refused order is not an order


def test_orders_after_the_last_day_are_refused(market: MarketData) -> None:
    session = ArenaSession(market, ["a"], start=len(market) - 2)
    app = build_server(session, SETTINGS, url=URL).streamable_http_app(
        json_response=True, stateless_http=True
    )
    with TestClient(app, base_url=URL) as http:
        arena = Arena(http, session)
        assert arena.ok("a", "place_order", allocations=[], **ORDER)["day_advanced"] is True
        assert arena.ok("a", "get_market_data")["finished"] is True
        assert "Oturum bitti" in arena.refused("a", "place_order", allocations=[], **ORDER)


def test_market_data_is_what_llm_agents_see_anonymised(arena: Arena, market: MarketData) -> None:
    result = arena.call("a", "get_market_data")
    data = result["structuredContent"]
    view = MarketView(market, START)
    assert data["day"] == 0
    assert data["fear_greed_index"] == view.fear_greed
    assert data["trading_cost_pct"] == 0.15
    assert data["assets"] == {
        "ASSET_A": asset_features(view, Asset.BTC),
        "ASSET_B": asset_features(view, Asset.ETH),
    }
    text = json.dumps(result)
    assert "BTC" not in text
    assert "ETH" not in text
    assert "2025" not in text  # no calendar dates


def test_tools_cannot_see_past_the_current_day(market: MarketData) -> None:
    """Two markets that differ only after today give byte-identical answers today."""
    crash = Bar(1.0, 1.0, 1.0, 1.0, 1.0)
    other = replace(
        market,
        bars={
            a: (*bars[: START + 1], *[crash] * (len(market) - START - 1))
            for a, bars in market.bars.items()
        },
        fear_greed=(*market.fear_greed[: START + 1], *[1] * (len(market) - START - 1)),
    )
    answers: list[list[dict[str, Any]]] = []
    for m in (market, other):
        for arena in serve(m):
            answers.append([arena.call("a", "get_market_data"), arena.call("a", "get_portfolio")])
    assert answers[0] == answers[1]

    # ... and once the day has advanced, the difference is visible.
    after: list[dict[str, Any]] = []
    for m in (market, other):
        for arena in serve(m):
            arena.ok("a", "place_order", allocations=[], **ORDER)
            arena.ok("b", "place_order", allocations=[], **ORDER)
            after.append(arena.ok("a", "get_market_data"))
    assert after[0] != after[1]


# ---------------------------------------------------------------- CLI


@pytest.fixture
def snapshot(tmp_path: Path) -> Path:
    start = SPLITS[Split.VALIDATION].start - timedelta(days=40)
    write_snapshot(synthetic_frame(start, 40 + 182), tmp_path / "snap", source="synthetic")
    return tmp_path / "snap"


def test_cli_token_names_one_agent(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "get_settings", lambda: SETTINGS)
    cli.main(["mcp", "token", "--agent", "mcp-guest", "--days", "1"])
    token = capsys.readouterr().out.strip()
    assert decode_agent_token(SETTINGS, token)[0] == "mcp-guest"


def test_cli_serves_a_replay_of_the_validation_split(
    snapshot: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    served: list[tuple[Any, str, int]] = []
    monkeypatch.setattr(cli, "get_settings", lambda: SETTINGS)
    monkeypatch.setattr(
        "uvicorn.run",
        lambda app, host, port: served.append((app, host, port)),  # pyright: ignore[reportUnknownLambdaType, reportUnknownArgumentType]
    )
    cli.main(["--snapshot", str(snapshot), "mcp", "serve", "--port", "8765", "--agents", "a", "b"])
    app, host, port = served[0]
    assert (host, port) == ("127.0.0.1", 8765)
    token = issue_agent_token(SETTINGS, "b", DAY)
    with TestClient(app, base_url=URL) as http:
        response = http.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "get_portfolio", "arguments": {}},
            },
            headers={
                "Accept": "application/json, text/event-stream",
                "Authorization": f"Bearer {token}",
            },
        )
    assert response.json()["result"]["structuredContent"]["agent_id"] == "b"


def test_cli_never_serves_the_sealed_test_split(
    snapshot: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CI", raising=False)
    with pytest.raises(SystemExit):
        cli.main(["--snapshot", str(snapshot), "mcp", "serve", "--split", "test"])


def test_cli_refuses_a_public_server_with_the_placeholder_secret(
    snapshot: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "get_settings", lambda: Settings(_env_file=None))  # pyright: ignore[reportCallIssue]
    with pytest.raises(SystemExit, match="MINDEX_JWT_SECRET"):
        cli.mcp_app(snapshot, Split.VALIDATION, ["a"], "0.0.0.0", 8765)  # noqa: S104
