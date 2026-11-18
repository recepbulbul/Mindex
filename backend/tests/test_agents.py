import json
import uuid
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from conftest import synthetic_frame
from mindex import cli
from mindex.agents.base import AgentKind
from mindex.agents.llm import (
    DECISION_V1,
    DECISION_V2,
    PERSONAS,
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    LlamaCppClient,
    LLMAgent,
    LLMUnavailableError,
    RecalledLesson,
    anonymise,
    build_messages,
    deanonymise,
)
from mindex.agents.rule import BuyAndHoldAgent, EqualWeightAgent, MovingAverageCrossAgent
from mindex.config import get_settings
from mindex.data.splits import Split
from mindex.domain.decision import Asset, parse_decision
from mindex.sim.engine import ExecutionCosts, Observation, Portfolio, Simulator
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
    chat = FakeChat(["{not json", "", bad])  # invalid output: the safe default (NF2)
    agent = LLMAgent(chat, persona="risk-averse", max_retries=2)
    assert agent.decide(obs(market, 40)) is None
    assert agent.stats.holds == 1
    assert agent.stats.attempts == [3]
    assert len(agent.stats.latencies_ms) == 3


def test_unreachable_llm_stops_instead_of_holding(market: MarketData) -> None:
    # A down server is not a model answer: holding would record a fake "held" run.
    agent = LLMAgent(FakeChat([LLMUnavailableError("connection refused")]), max_retries=2)
    with pytest.raises(LLMUnavailableError):
        agent.decide(obs(market, 40))
    assert agent.stats.holds == 0


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


def test_baseline_with_unreachable_llm_exits_with_a_message(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from mindex import cli

    def down(*_: object, **__: object) -> None:
        raise LLMUnavailableError("connection refused")

    monkeypatch.setattr(cli, "baseline", down)
    with pytest.raises(SystemExit) as exited:
        cli.main(["baseline", "--llm"])
    assert exited.value.code != 0
    assert "LLM sunucusuna ulaşılamadı" in str(exited.value.code)
    assert "Traceback" not in capsys.readouterr().err


# --- decision-v1 / decision-v2 prompts ------------------------------------------


def lesson(
    day: date, text: str = "ASSET_A girişi %3,2 kaybettirdi; girmemek daha iyiydi."
) -> RecalledLesson:
    return RecalledLesson(uuid.uuid4(), text, 0.8312, day, "bear")


def test_decision_v1_prompt_is_unchanged(market: MarketData) -> None:
    """The C0 baseline (`decision-v1`) must stay reproducible byte for byte (NF5)."""
    codes = anonymise(market.assets)
    messages = build_messages(obs(market, 40, {Asset.BTC: 0.5}, step=9), "momentum", codes)
    assert messages[0]["content"] == SYSTEM_PROMPT.format(persona=PERSONAS["momentum"])
    user = json.loads(messages[1]["content"])
    assert set(user) == {"day", "fear_greed_index", "assets", "portfolio"}
    assert (
        build_messages(
            obs(market, 40, {Asset.BTC: 0.5}, step=9), "momentum", codes, prompt_version=DECISION_V1
        )
        == messages
    )


def test_decision_v2_adds_hold_option_cost_and_days_since_trade(market: MarketData) -> None:
    codes = anonymise(market.assets)
    o = Observation(MarketView(market, 40), 9, Portfolio(10_000.0), {Asset.BTC: 0.5}, 10_000.0, 4)
    messages = build_messages(
        o, "momentum", codes, prompt_version=DECISION_V2, costs=ExecutionCosts(0.001, 5)
    )
    assert messages[0]["content"].startswith(SYSTEM_PROMPT.format(persona=PERSONAS["momentum"]))
    assert "Keeping your current portfolio is a valid" in messages[0]["content"]
    assert "0.15%" in messages[0]["content"]  # 0.1 % commission + 5 bp slippage
    assert "lessons" not in messages[0]["content"]  # C0: no memory, no mention of it
    user = json.loads(messages[1]["content"])
    assert (user["days_since_trade"], user["trading_cost_pct"]) == (4, 0.15)
    assert "lessons" not in user
    never = Observation(MarketView(market, 40), 9, Portfolio(10_000.0), {}, 10_000.0)
    never_user = json.loads(
        build_messages(never, "momentum", codes, prompt_version=DECISION_V2)[1]["content"]
    )
    assert never_user["days_since_trade"] is None
    assert never_user["trading_cost_pct"] == 0.15  # default costs


def test_decision_v2_hold_by_echoing_the_weights_is_always_a_valid_decision() -> None:
    """The prompt tells the model to hold by returning its current weights. Rounded to nearest,
    a fully invested portfolio can show weights summing to 1.0001, which `Decision` rejects
    (found with the real model: every retry echoed it, so the agent was recorded as held)."""
    assets = (Asset.BTC, Asset.ETH, Asset.SOL)
    three = MarketData.from_frame(synthetic_frame(date(2025, 1, 1), 60, assets))
    weights = {Asset.BTC: 0.33336, Asset.ETH: 0.33336, Asset.SOL: 0.33328}  # sum 1.0
    assert sum(round(w, 4) for w in weights.values()) > 1  # what decision-v1 would show
    codes = anonymise(three.assets)
    for version in (DECISION_V1, DECISION_V2):
        messages = build_messages(
            obs(three, 40, weights), "momentum", codes, prompt_version=version
        )
        shown = json.loads(messages[1]["content"])["portfolio"]["weights"]
        echo = [{"asset": code, "weight": w} for code, w in shown.items()]
        reply = json.dumps({"allocations": echo, "confidence": 0.5, "rationale": "Aynen koru."})
        decision = parse_decision(deanonymise(reply, codes)) if version == DECISION_V2 else None
        if version == DECISION_V2:
            assert decision is not None
            assert decision.total_weight <= 1.0
            assert decision.weights() == {a: pytest.approx(w, abs=1e-3) for a, w in weights.items()}
        else:
            with pytest.raises(ValueError, match="no leverage"):
                parse_decision(deanonymise(reply, codes))


def test_decision_v2_lessons_are_listed_with_age_and_stay_anonymous(market: MarketData) -> None:
    codes = anonymise(market.assets)
    o = obs(market, 40, step=9)
    known = o.view.day.replace(day=1)
    messages = build_messages(
        o, "momentum", codes, prompt_version=DECISION_V2, lessons=[lesson(known)]
    )
    assert "`lessons` are post-mortems of your own" in messages[0]["content"]
    user = json.loads(messages[1]["content"])
    assert user["lessons"] == [
        {
            "lesson": "ASSET_A girişi %3,2 kaybettirdi; girmemek daha iyiydi.",
            "relevance": 0.831,
            "days_ago": (o.view.day - known).days,
            "regime": "bear",
        }
    ]
    # C1 before any lesson exists is still a memory prompt: an empty list, not C0's prompt.
    empty = build_messages(o, "momentum", codes, prompt_version=DECISION_V2, lessons=[])
    assert json.loads(empty[1]["content"])["lessons"] == []
    assert "`lessons` are post-mortems" in empty[0]["content"]
    text = " ".join(m["content"] for m in messages)
    for leak in ("BTC", "ETH", "2025"):
        assert leak not in text


def test_prompt_version_rules(market: MarketData) -> None:
    codes = anonymise(market.assets)
    with pytest.raises(ValueError, match="unknown prompt version"):
        build_messages(obs(market, 40), "momentum", codes, prompt_version="decision-v9")
    with pytest.raises(ValueError, match="decision-v2"):
        build_messages(obs(market, 40), "momentum", codes, lessons=[])  # v1 has no memory
    with pytest.raises(ValueError, match="unknown prompt version"):
        LLMAgent(FakeChat([GOOD]), prompt_version="decision-v9")
    with pytest.raises(ValueError, match="decision-v2"):
        LLMAgent(FakeChat([GOOD]), recall=lambda o: [])
    assert PROMPT_VERSION == DECISION_V2  # new experiments run v2; v1 stays for stored C0 runs


def test_llm_agent_recalls_before_deciding_and_exposes_the_lessons(market: MarketData) -> None:
    chat = FakeChat([GOOD])
    seen: list[date] = []
    known = date(2025, 1, 5)

    def recall(o: Observation) -> list[RecalledLesson]:
        seen.append(o.view.day)
        return [lesson(known)]

    agent = LLMAgent(chat, prompt_version=DECISION_V2, recall=recall)
    assert agent.decide(obs(market, 40)) is not None
    assert seen == [obs(market, 40).view.day]
    assert [x.day for x in agent.last_lessons] == [known]
    user = json.loads(chat.messages[0][1]["content"])
    assert len(user["lessons"]) == 1
    # No memory: nothing recalled, and the prompt has no `lessons` key at all.
    plain = LLMAgent(FakeChat([GOOD]), prompt_version=DECISION_V2)
    plain.decide(obs(market, 40))
    assert plain.last_lessons == ()


class BenchClient:
    model = "bench-model"

    def __init__(self) -> None:
        self.messages: list[list[dict[str, str]]] = []

    def complete(self, messages: list[dict[str, str]], *, schema: Mapping[str, Any]) -> str:
        self.messages.append(messages)
        return GOOD


def test_bench_llm_times_the_memory_prompt_into_its_own_file(
    market: MarketData, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = BenchClient()

    def fake_market(snapshot: Path, split: Split, unseal: bool) -> tuple[MarketData, int]:
        return market, 31

    monkeypatch.setattr(cli, "_market", fake_market)
    monkeypatch.setattr(cli, "_llm_client", lambda: client)

    # C1's context: decision-v2 with two lessons; the C0 baseline file stays untouched.
    cli.bench_llm(tmp_path / "unused", tmp_path, 3, DECISION_V2, 2)
    assert not (tmp_path / "llm-benchmark.json").exists()
    result = json.loads((tmp_path / "llm-benchmark-decision-v2-lessons2.json").read_text("utf-8"))
    assert (result["prompt_version"], result["lessons"], result["calls"]) == (DECISION_V2, 2, 3)
    assert result["invalid_json"] == 0
    assert all(len(json.loads(m[1]["content"])["lessons"]) == 2 for m in client.messages)

    # The default is the C0 baseline: decision-v1, its own file, no lessons in the prompt.
    client.messages.clear()
    cli.bench_llm(tmp_path / "unused", tmp_path, 2)
    assert (tmp_path / "llm-benchmark.json").exists()
    assert all("lessons" not in json.loads(m[1]["content"]) for m in client.messages)
    assert all(
        SYSTEM_PROMPT.format(persona=PERSONAS["momentum"]) == m[0]["content"]
        for m in client.messages
    )


@pytest.mark.model
def test_real_model_answers_the_memory_prompt(market: MarketData) -> None:
    """Needs a running `llama-server` with the Qwen model (`uv run pytest -m model --no-cov`)."""
    s = get_settings()
    client = LlamaCppClient(s.llm_base_url, s.llm_model, timeout=s.llm_timeout_seconds)
    known = obs(market, 40).view.day.replace(day=1)
    agent = LLMAgent(
        client, prompt_version=DECISION_V2, recall=lambda o: [lesson(known), lesson(known)]
    )
    decision = agent.decide(
        Observation(MarketView(market, 40), 9, Portfolio(10_000.0), {Asset.BTC: 0.5}, 10_000.0, 4)
    )
    assert decision is not None  # valid JSON under the schema, within the retries
    print(decision, agent.stats.attempts, agent.stats.latencies_ms)
