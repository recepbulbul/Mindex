"""First LLM agent (baseline, condition C0: no memory, no forum).

Observation -> anonymised prompt -> llama.cpp (thinking off, JSON-schema constrained)
-> Pydantic validation with retries -> hold on failure (NF2, flow 2 in docs/03-flows.md).
Asset names become `ASSET_A`... and dates become day numbers (look-ahead protocol).
"""

import json
import math
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass, field
from itertools import pairwise
from statistics import fmean, pstdev
from typing import Any, Protocol, cast

import structlog

from mindex.agents.base import AgentKind, BaseAgent
from mindex.domain.decision import Asset, Decision, DecisionResult, decide_with_retries
from mindex.sim.engine import Observation
from mindex.sim.market import MarketView

PROMPT_VERSION = "decision-v1"
LOOKBACK_DAYS = 30

PERSONAS: dict[str, str] = {
    "momentum": "You follow trends: overweight assets with strong recent momentum, "
    "cut assets whose trend is breaking down.",
    "mean-reversion": "You buy sharp sell-offs expecting a rebound and trim assets after "
    "unusually strong rallies.",
    "sentiment": "You trade on market sentiment: the Fear & Greed index and perpetual "
    "funding rates (crowded longs are a warning sign).",
    "risk-averse": "You protect capital first: hold cash when volatility is high or "
    "trends are down, and keep position sizes modest.",
}

SYSTEM_PROMPT = """You are a crypto portfolio manager in a daily, long-only, unleveraged simulation.
{persona}
Each day you receive anonymised market data and return target portfolio weights for the next
open. Weights are fractions of total equity in [0, 1] and must sum to at most 1; the rest is
held as cash. Omit assets you do not want to hold. Use only the data given; asset names and
dates are anonymised on purpose. Write the rationale in Turkish, 1-3 sentences, citing the
numbers you relied on."""

log = structlog.get_logger(__name__)


class ChatClient(Protocol):
    def complete(self, messages: list[dict[str, str]], *, schema: Mapping[str, Any]) -> str: ...


class LLMUnavailableError(RuntimeError):
    pass


class LlamaCppClient:
    """OpenAI-compatible `/chat/completions` client for llama.cpp `llama-server`.

    Thinking is disabled and output is constrained by the JSON schema (ADR-4).
    """

    def __init__(self, base_url: str, model: str, *, timeout: float = 30.0, seed: int = 0) -> None:
        if not base_url.startswith(("http://", "https://")):
            raise ValueError("base_url must be an http(s) URL")
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.model = model
        self.timeout = timeout
        self.seed = seed

    def complete(self, messages: list[dict[str, str]], *, schema: Mapping[str, Any]) -> str:
        body = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.0,
            "seed": self.seed,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "decision", "schema": schema, "strict": True},
            },
            "chat_template_kwargs": {"enable_thinking": False},
        }
        req = urllib.request.Request(  # noqa: S310 (scheme validated in __init__)
            self.url,
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310
                payload = cast(dict[str, Any], json.loads(resp.read()))
        except (urllib.error.URLError, TimeoutError) as exc:
            raise LLMUnavailableError(str(exc)) from exc
        return cast(str, payload["choices"][0]["message"]["content"])


def anonymise(assets: tuple[Asset, ...]) -> dict[Asset, str]:
    return {a: f"ASSET_{chr(ord('A') + i)}" for i, a in enumerate(assets)}


def decision_schema(codes: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["allocations", "confidence", "rationale"],
        "properties": {
            "allocations": {
                "type": "array",
                "maxItems": len(codes),
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["asset", "weight"],
                    "properties": {
                        "asset": {"type": "string", "enum": codes},
                        "weight": {"type": "number", "minimum": 0, "maximum": 1},
                    },
                },
            },
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "rationale": {"type": "string", "minLength": 10, "maxLength": 2000},
        },
    }


def _pct(x: float) -> float:
    return round(x * 100, 2)


def asset_features(view: MarketView, asset: Asset) -> dict[str, Any]:
    closes = view.closes(asset, LOOKBACK_DAYS + 1)
    rets = [b / a - 1 for a, b in pairwise(closes)]
    sma10 = fmean(closes[-10:])
    funding = view.funding_rate(asset)
    return {
        "daily_returns_pct_30d": [_pct(r) for r in rets],
        "return_7d_pct": _pct(closes[-1] / closes[-8] - 1) if len(closes) >= 8 else None,
        "return_30d_pct": _pct(closes[-1] / closes[0] - 1),
        "volatility_30d_ann_pct": _pct(pstdev(rets) * math.sqrt(365)) if len(rets) > 1 else None,
        "close_vs_sma10_pct": _pct(closes[-1] / sma10 - 1),
        "close_vs_sma30_pct": _pct(closes[-1] / fmean(closes[-30:]) - 1),
        "funding_rate_pct": None if funding is None else round(funding * 100, 4),
    }


def build_messages(
    obs: Observation, persona: str, codes: Mapping[Asset, str]
) -> list[dict[str, str]]:
    view = obs.view
    user = {
        "day": obs.step,
        "fear_greed_index": view.fear_greed,
        "assets": {codes[a]: asset_features(view, a) for a in view.assets},
        "portfolio": {
            "weights": {codes[a]: round(w, 4) for a, w in obs.weights.items()},
            "cash_weight": round(1 - sum(obs.weights.values()), 4),
        },
    }
    return [
        {"role": "system", "content": SYSTEM_PROMPT.format(persona=PERSONAS[persona])},
        {"role": "user", "content": json.dumps(user, separators=(",", ":"))},
    ]


def deanonymise(raw: str, codes: Mapping[Asset, str]) -> str:
    """Map `ASSET_x` back to real symbols; anything malformed is passed on to fail validation."""
    reverse = {code: str(asset) for asset, code in codes.items()}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    if isinstance(data, dict):
        allocations = cast(dict[str, Any], data).get("allocations")
        if isinstance(allocations, list):
            for item in cast(list[Any], allocations):
                if isinstance(item, dict):
                    alloc = cast(dict[str, Any], item)
                    code = alloc.get("asset")
                    if isinstance(code, str) and code in reverse:
                        alloc["asset"] = reverse[code]
    return json.dumps(data)


@dataclass(slots=True)
class CallStats:
    latencies_ms: list[int] = field(default_factory=list[int])
    attempts: list[int] = field(default_factory=list[int])
    holds: int = 0


class LLMAgent(BaseAgent):
    kind = AgentKind.LLM

    def __init__(
        self,
        client: ChatClient,
        *,
        persona: str = "momentum",
        max_retries: int = 2,
        agent_id: str | None = None,
    ) -> None:
        if persona not in PERSONAS:
            raise ValueError(f"unknown persona {persona!r}")
        super().__init__(agent_id or f"llm-{persona}")
        self.client = client
        self.persona = persona
        self.max_retries = max_retries
        self.stats = CallStats()

    def decide(self, obs: Observation) -> Decision | None:
        codes = anonymise(obs.view.assets)
        messages = build_messages(obs, self.persona, codes)
        schema = decision_schema(list(codes.values()))

        def generate(attempt: int) -> str:
            started = time.perf_counter()
            try:
                raw = self.client.complete(messages, schema=schema)
            except LLMUnavailableError as exc:
                log.warning("llm_unavailable", agent=self.agent_id, attempt=attempt, error=str(exc))
                raw = ""
            self.stats.latencies_ms.append(round((time.perf_counter() - started) * 1000))
            return deanonymise(raw, codes)

        result: DecisionResult = decide_with_retries(generate, max_retries=self.max_retries)
        self.stats.attempts.append(result.attempts)
        if result.held_position:
            self.stats.holds += 1
        log.info(
            "llm_decision",
            agent=self.agent_id,
            day=obs.step,
            prompt_version=PROMPT_VERSION,
            attempts=result.attempts,
            held_position=result.held_position,
        )
        return result.decision
