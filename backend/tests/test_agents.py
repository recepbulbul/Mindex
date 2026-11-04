import json
from collections.abc import Mapping
from typing import Any

import pytest

from mindex.agents.base import AgentKind
from mindex.agents.llm import (
    PERSONAS,
    PROMPT_VERSION,
    LlamaCppClient,
    LLMAgent,
    LLMUnavailableError,
    anonymise,
    build_messages,
    deanonymise,
)
from mindex.agents.rule import BuyAndHoldAgent, EqualWeightAgent, MovingAverageCrossAgent
from mindex.domain.decision import Asset
from mindex.sim.engine import Observation, Portfolio, Simulator
from mindex.sim.market import MarketData, MarketView


def obs(
    market: MarketData, t: int, weights: dict[Asset, float] | None = None, step: int = 0
) -> Observation:
    return Observation(MarketView(market, t), step, Portfolio(10_000.0), weights or {}, 10_000.0)


# --- rule agents ------------------------------------------------------------


def test_buy_and_hold_buys_once(market: MarketData) -> None:
    agent = BuyAndHoldAgent()
    assert agent.agent_id == "buy-hold-btc"
    assert agent.kind is AgentKind.RULE
    first = agent.decide(obs(market, 0))
    assert first is not None
    assert first.weights() == {Asset.BTC: 1.0}
    assert agent.decide(obs(market, 1, {Asset.BTC: 0.99})) is None
    assert repr(agent) == "BuyAndHoldAgent('buy-hold-btc')"


def test_equal_weight_rebalances_periodically(market: MarketData) -> None:
    agent = EqualWeightAgent(rebalance_days=7)
    d = agent.decide(obs(market, 0, step=14))
    assert d is not None
    assert d.weights() == {Asset.BTC: 0.5, Asset.ETH: 0.5}
    assert agent.decide(obs(market, 0, step=3)) is None
    with pytest.raises(ValueError, match="rebalance_days"):
        EqualWeightAgent(rebalance_days=0)


def test_ma_cross_follows_trend(market: MarketData) -> None:
    agent = MovingAverageCrossAgent(short=5, long=20)
    assert agent.decide(obs(market, 10)) is None  # warm-up
    d = agent.decide(obs(market, 40))
    assert d is not None
    assert Asset.BTC in d.weights()  # BTC trends up in the synthetic market
    assert d.weights()[Asset.BTC] == pytest.approx(0.5)
    held = dict.fromkeys(d.weights(), 0.5)
    assert agent.decide(obs(market, 40, held)) is None  # unchanged signal: no trade
    with pytest.raises(ValueError, match="short < long"):
        MovingAverageCrossAgent(short=30, long=10)


def test_rule_agents_run_end_to_end(market: MarketData) -> None:
    agents = [BuyAndHoldAgent(), EqualWeightAgent(), MovingAverageCrossAgent()]
    state = Simulator(market, agents, start=31).run()
    btc = state.books["buy-hold-btc"]
    assert btc.equity[-1] > btc.equity[0]  # BTC rises 1 %/day in the fixture
    assert len(btc.fills) == 1


# --- LLM agent --------------------------------------------------------------


class FakeChat:
    def __init__(self, replies: list[str | Exception]) -> None:
        self.replies = replies
        self.messages: list[list[dict[str, str]]] = []
        self.schemas: list[Mapping[str, Any]] = []

    def complete(self, messages: list[dict[str, str]], *, schema: Mapping[str, Any]) -> str:
        self.messages.append(messages)
        self.schemas.append(schema)
        reply = self.replies[min(len(self.messages) - 1, len(self.replies) - 1)]
        if isinstance(reply, Exception):
            raise reply
        return reply


GOOD = json.dumps(
    {
        "allocations": [{"asset": "ASSET_A", "weight": 0.6}],
        "confidence": 0.7,
        "rationale": "ASSET_A 30 günde %35 yükseldi, momentum güçlü.",
    }
)


def test_prompt_is_anonymised(market: MarketData) -> None:
    codes = anonymise(market.assets)
    assert codes == {Asset.BTC: "ASSET_A", Asset.ETH: "ASSET_B"}
    messages = build_messages(obs(market, 40, {Asset.BTC: 0.5}, step=9), "momentum", codes)
    text = " ".join(m["content"] for m in messages)
    for leak in ("BTC", "ETH", "2025"):
        assert leak not in text
    user = json.loads(messages[1]["content"])
    assert user["day"] == 9
    assert len(user["assets"]["ASSET_A"]["daily_returns_pct_30d"]) == 30
    assert user["portfolio"]["weights"] == {"ASSET_A": 0.5}


def test_deanonymise() -> None:
    codes = {Asset.BTC: "ASSET_A"}
    assert json.loads(deanonymise(GOOD, codes))["allocations"][0]["asset"] == "BTC"
    assert deanonymise("{broken", codes) == "{broken"
    assert json.loads(deanonymise('{"allocations": [1, {"asset": 5}]}', codes)) == {
        "allocations": [1, {"asset": 5}]
    }


def test_llm_agent_decides(market: MarketData) -> None:
    chat = FakeChat([GOOD])
    agent = LLMAgent(chat)
    assert agent.agent_id == "llm-momentum"
    d = agent.decide(obs(market, 40))
    assert d is not None
    assert d.weights() == {Asset.BTC: 0.6}
    assert chat.schemas[0]["properties"]["allocations"]["items"]["properties"]["asset"]["enum"] == [
        "ASSET_A",
        "ASSET_B",
    ]
    assert agent.stats.attempts == [1]
    assert PROMPT_VERSION.startswith("decision-v")


def test_llm_agent_retries_then_holds(market: MarketData) -> None:
    bad = json.dumps({"allocations": [{"asset": "ASSET_A", "weight": 1.5}]})
    chat = FakeChat(["{not json", LLMUnavailableError("timeout"), bad])
    agent = LLMAgent(chat, persona="risk-averse", max_retries=2)
    assert agent.decide(obs(market, 40)) is None
    assert agent.stats.holds == 1
    assert agent.stats.attempts == [3]
    assert len(agent.stats.latencies_ms) == 3


def test_llm_agent_rejects_unknown_persona() -> None:
    with pytest.raises(ValueError, match="persona"):
        LLMAgent(FakeChat([GOOD]), persona="yolo")
    assert set(PERSONAS) == {"momentum", "mean-reversion", "sentiment", "risk-averse"}


def test_llama_client_validates_url() -> None:
    with pytest.raises(ValueError, match="http"):
        LlamaCppClient("file:///etc/passwd", "m")
    assert LlamaCppClient("http://localhost:8080/v1/", "m").url.endswith("/v1/chat/completions")


def test_llama_client_reports_unreachable_server() -> None:
    client = LlamaCppClient("http://127.0.0.1:9/v1", "m", timeout=1.0)
    with pytest.raises(LLMUnavailableError):
        client.complete([{"role": "user", "content": "hi"}], schema={})
