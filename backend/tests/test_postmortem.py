"""Lesson writing: fake `ChatClient` for accept / retry / reject / bad JSON / anonymisation,
a DB test for what gets stored, and one real-model test (`-m model`)."""

import json
import uuid
from collections.abc import Mapping
from datetime import date
from typing import Any, cast

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from mindex.agents.llm import LlamaCppClient, LLMUnavailableError
from mindex.config import get_settings
from mindex.db.models import MemoryRow
from mindex.domain.decision import Asset
from mindex.domain.regime import Regime
from mindex.memory.embedder import HashEmbedder
from mindex.memory.store import MemoryStore
from mindex.postmortem.counterfactual import Counterfactual
from mindex.postmortem.lesson import (
    POSTMORTEM_PROMPT_VERSION,
    PostmortemResult,
    check_consistency,
    consistency_rate,
    lesson_schema,
    percent_claims,
    postmortem,
    write_lesson,
)
from test_memory_store import make_agents

ASSETS = (Asset.BTC, Asset.ETH)
EXIT = date(2025, 3, 5)
# ETH lost 10 %; half size -5 %, 5 % stop-loss -5 %, skipping (0 %) was best.
CF = Counterfactual(
    asset=Asset.ETH,
    entry_day=date(2025, 3, 2),
    exit_day=EXIT,
    holding_days=3,
    stop_pct=0.05,
    cost=1000.0,
    actual=-0.10,
    skip=0.0,
    half=-0.05,
    stop_loss=-0.05,
    stop_day=date(2025, 3, 4),
)
GOOD_TEXT = (
    "ASSET_B pozisyonu %10 kaybettirdi; %5 zarar-kes kaybı %5'e indirirdi, girmemek en iyisiydi."
)


def reply(
    lesson: str = GOOD_TEXT,
    *,
    outcome: str = "loss",
    best: str = "skip",
    importance: float = 0.7,
    regime: str = "bear",
) -> str:
    return json.dumps(
        {
            "lesson": lesson,
            "importance": importance,
            "regime": regime,
            "outcome": outcome,
            "best_scenario": best,
        }
    )


class FakeClient:
    def __init__(self, *replies: str | Exception) -> None:
        self.replies = replies
        self.messages: list[list[dict[str, str]]] = []

    def complete(self, messages: list[dict[str, str]], *, schema: Mapping[str, Any]) -> str:
        assert schema == lesson_schema()
        self.messages.append(messages)
        out = self.replies[min(len(self.messages) - 1, len(self.replies) - 1)]
        if isinstance(out, Exception):
            raise out
        return out


def test_accepts_consistent_lesson_and_prompt_is_anonymised() -> None:
    client = FakeClient(reply())
    result = write_lesson(client, CF, assets=ASSETS, regime_hint=Regime.BEAR, max_retries=2)
    assert result.accepted
    assert result.reason is None
    assert result.draft is not None
    assert result.draft.regime is Regime.BEAR
    assert len(result.attempts) == 1
    prompt = json.dumps(client.messages[0])
    assert "ASSET_B" in prompt
    for leak in ("ETH", "BTC", "2025", "03-05"):
        assert leak not in prompt
    payload = json.loads(client.messages[0][1]["content"])
    assert payload["returns_pct"] == {"actual": -10.0, "skip": 0.0, "half": -5.0, "stop_loss": -5.0}
    assert payload["holding_days"] == 3
    assert POSTMORTEM_PROMPT_VERSION == "postmortem-v1"


def test_retries_with_reason_then_accepts() -> None:
    client = FakeClient(reply("ASSET_B pozisyonu %12 kaybettirdi, girmemek daha iyiydi."), reply())
    result = write_lesson(client, CF, assets=ASSETS, max_retries=2)
    assert result.accepted
    assert [a.consistent for a in result.attempts] == [False, True]
    feedback = client.messages[1][-1]["content"]
    assert "reddedildi" in feedback
    assert "%12" in feedback


def test_rejects_after_max_retries_with_reason() -> None:
    bad = reply("ASSET_B pozisyonu %3 kazandırdı, aynen devam etmeli.", outcome="gain")
    client = FakeClient(bad)
    result = write_lesson(client, CF, assets=ASSETS, max_retries=2)
    assert not result.accepted
    assert len(result.attempts) == 3
    assert result.reason is not None
    assert "%3" in result.reason


def test_default_retries_come_from_settings() -> None:
    client = FakeClient(reply("ASSET_B için açık bir ders yok, sadece kötü bir gündü."))
    result = write_lesson(client, CF, assets=ASSETS)
    assert len(result.attempts) == get_settings().llm_max_retries + 1


def test_bad_json_and_unavailable_llm_count_as_failed_attempts() -> None:
    client = FakeClient("bu json değil", LLMUnavailableError("kapalı"), reply())
    result = write_lesson(client, CF, assets=ASSETS, max_retries=2)
    assert result.accepted
    assert [a.schema_valid for a in result.attempts] == [False, False, True]


def test_schema_bounds_reject_instead_of_db_error() -> None:
    client = FakeClient(reply("kısa"), reply(importance=1.5))
    result = write_lesson(client, CF, assets=ASSETS, max_retries=1)
    assert not result.accepted
    assert all(not a.schema_valid for a in result.attempts)


@pytest.mark.parametrize(
    ("text", "kwargs", "reason"),
    [
        ("BTC pozisyonu %10 kaybettirdi; girmemek en iyisiydi.", {}, "gerçek"),
        ("Bitcoin gibi varlıklarda %10 kayıp yaşandı, girmemeliydi.", {}, "gerçek"),
        ("ASSET_B pozisyonu %10 kazandırdı; girmemek en iyisiydi.", {}, "yön"),
        ("ASSET_B pozisyonu kayıp verdi; girmemek en iyisiydi.", {}, "yüzde"),
        ("ASSET_B pozisyonu %10 kaybettirdi; girmemek en iyisiydi.", {"outcome": "gain"}, "yön"),
        ("ASSET_B pozisyonu %10 kaybettirdi; yarım boyut iyiydi.", {"best": "half"}, "senaryo"),
        ("ASSET_B pozisyonu +%10 kazandırdı, girmemek en iyisiydi.", {}, "uyuşmuyor"),
        ("ASSET_B %10 kaybettirdi, girmemek %7 daha iyiydi.", {}, "uyuşmuyor"),
    ],
)
def test_inconsistent_lessons(text: str, kwargs: dict[str, Any], reason: str) -> None:
    result = write_lesson(FakeClient(reply(text, **kwargs)), CF, assets=ASSETS, max_retries=0)
    assert not result.accepted
    assert result.reason is not None
    assert reason in result.reason


@pytest.mark.parametrize(
    "text",
    [
        GOOD_TEXT,
        "ASSET_B -%10 getiri verdi; zarar-kes %5 eşiğiyle -%5 olurdu.",
        "ASSET_B 10.0% düştü, yüzde 5 kayıpla çıkmak daha iyiydi.",
        "ASSET_B %10,0 kaybettirdi; yarım boyut %5 daha az kaybettirirdi.",  # a difference
        "ASSET_B sol tarafta kaldı: %10 zarar, zarar-kes %5 ile kaybı yarıya indirirdi.",
    ],
)
def test_consistent_lessons(text: str) -> None:
    result = write_lesson(FakeClient(reply(text)), CF, assets=ASSETS, max_retries=0)
    assert result.accepted, result.reason


def test_signed_claim_must_match_sign() -> None:
    result = write_lesson(
        FakeClient(reply("ASSET_B pozisyonu -%5 eşiğiyle durmalıydı, %10 kaybetti.")),
        CF,
        assets=ASSETS,
        max_retries=0,
    )
    assert result.accepted  # -5 % is the half / stop-loss return
    gain = Counterfactual(**_gain_kwargs())
    draft_text = "ASSET_B -%4 getiri verdi, zarar-kes gereksizdi."
    out = write_lesson(
        FakeClient(reply(draft_text, outcome="gain", best="actual")),
        gain,
        assets=ASSETS,
        max_retries=0,
    )
    assert not out.accepted  # the table has +4 %, not -4 %


def _gain_kwargs() -> dict[str, Any]:
    return {
        "asset": Asset.BTC,
        "entry_day": date(2025, 3, 2),
        "exit_day": EXIT,
        "holding_days": 3,
        "stop_pct": 0.05,
        "cost": 1000.0,
        "actual": 0.04,
        "skip": 0.0,
        "half": 0.02,
        "stop_loss": 0.04,
        "stop_day": None,
    }


def test_best_scenario_ties_accept_any() -> None:
    gain = Counterfactual(**_gain_kwargs())  # actual == stop_loss == 4 %
    for best in ("actual", "stop_loss"):
        out = write_lesson(
            FakeClient(
                reply(
                    "ASSET_A %4 kazandırdı; trend sürdükçe tutmak doğruydu.",
                    outcome="gain",
                    best=best,
                )
            ),
            gain,
            assets=ASSETS,
            max_retries=0,
        )
        assert out.accepted, out.reason


def test_percent_claims_parsing() -> None:
    claims = percent_claims(f"%5,2 ve 3.25% ile -%3, %-1, {chr(0x2212)}4 %, +%2 ve yüzde 7")
    assert [(c.value, c.decimals, c.signed) for c in claims] == [
        (5.2, 1, False),
        (3.25, 2, False),
        (-3.0, 0, True),
        (-1.0, 0, True),
        (-4.0, 0, True),
        (2.0, 0, True),
        (7.0, 0, False),
    ]


def test_consistency_rate_counts_schema_valid_attempts() -> None:
    accepted = write_lesson(
        FakeClient(reply("ASSET_B %12 kaybettirdi, girmemek iyiydi."), reply()),
        CF,
        assets=ASSETS,
        max_retries=2,
    )
    broken = write_lesson(FakeClient("{"), CF, assets=ASSETS, max_retries=0)
    assert consistency_rate([accepted, broken]) == pytest.approx(0.5)
    assert consistency_rate([broken]) is None
    assert consistency_rate([]) is None


def test_check_consistency_direct() -> None:
    result: PostmortemResult = write_lesson(FakeClient(reply()), CF, assets=ASSETS, max_retries=0)
    assert result.draft is not None
    assert check_consistency(result.draft, CF) is None


class RecordingStore:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

    def add(self, *args: Any) -> MemoryRow:
        self.calls.append(args)
        return MemoryRow()


def test_postmortem_passes_day_table_and_source_trade() -> None:
    store = RecordingStore()
    agent, trade = uuid.uuid4(), uuid.uuid4()
    result, row = postmortem(
        FakeClient(reply()),
        cast(MemoryStore, store),
        agent,
        CF,
        assets=ASSETS,
        max_retries=0,
        source_trade_id=trade,
    )
    assert result.accepted
    assert row is not None
    assert store.calls == [(agent, EXIT, GOOD_TEXT, CF.table(), Regime.BEAR, 0.7, trade)]


@pytest.mark.db
def test_accepted_lesson_is_stored_on_the_closing_day(db_session: Session) -> None:
    agent = make_agents(db_session, 1)[0]
    store = MemoryStore(db_session, HashEmbedder())
    result, row = postmortem(FakeClient(reply()), store, agent, CF, assets=ASSETS, max_retries=0)
    assert result.accepted
    assert row is not None
    stored = db_session.get(MemoryRow, row.id)
    assert stored is not None
    assert stored.day == EXIT
    assert stored.counterfactual == {"actual": -0.1, "skip": 0.0, "half": -0.05, "stop_loss": -0.05}
    assert stored.lesson == GOOD_TEXT
    assert stored.regime is Regime.BEAR
    assert float(stored.importance) == pytest.approx(0.7)
    # Learned at the close of the exit day: retrievable from the next day on only.
    assert store.search(agent, "zarar-kes", EXIT, Regime.BEAR, 5, True) == []
    hits = store.search(agent, "zarar-kes", date(2025, 3, 6), Regime.BEAR, 5, True)
    assert [h.memory.id for h in hits] == [row.id]


@pytest.mark.db
def test_rejected_lesson_is_not_stored(db_session: Session) -> None:
    agent = make_agents(db_session, 1)[0]
    store = MemoryStore(db_session, HashEmbedder())
    bad = FakeClient(reply("ASSET_B %3 kazandırdı, devam.", outcome="gain"))
    result, row = postmortem(bad, store, agent, CF, assets=ASSETS, max_retries=1)
    assert not result.accepted
    assert row is None
    count = db_session.scalar(
        select(func.count()).select_from(MemoryRow).where(MemoryRow.experiment_agent_id == agent)
    )
    assert count == 0


@pytest.mark.model
def test_real_model_writes_a_checked_lesson() -> None:
    """Needs a running `llama-server` with the Qwen model (`uv run pytest -m model --no-cov`)."""
    s = get_settings()
    client = LlamaCppClient(s.llm_base_url, s.llm_model, timeout=s.llm_timeout_seconds)
    result = write_lesson(client, CF, assets=ASSETS, regime_hint=Regime.BEAR)
    assert result.attempts
    assert any(a.schema_valid for a in result.attempts)
    if result.draft is not None:
        assert check_consistency(result.draft, CF) is None
    print(result.draft, [a.reason for a in result.attempts])


def _cf(**changes: Any) -> Counterfactual:
    return Counterfactual(**{**_gain_kwargs(), **changes})


# Stop-loss not triggered, so stop_loss == actual: the direction check must still apply.
UNTRIGGERED_LOSS = {"actual": -0.03, "half": -0.015, "stop_loss": -0.03, "stop_day": None}


@pytest.mark.parametrize(
    ("changes", "text", "outcome", "best"),
    [
        ({}, "ASSET_A pozisyonu %4 kaybettirdi; tutmak doğruydu.", "gain", "actual"),
        (
            UNTRIGGERED_LOSS,
            "ASSET_A pozisyonu %3 kazandırdı; girmemek en iyisiydi.",
            "loss",
            "skip",
        ),
        (UNTRIGGERED_LOSS, "ASSET_A için kazanç %3 oldu; girmemek en iyisiydi.", "loss", "skip"),
        ({}, "ASSET_A pozisyonunun zararı %4 oldu; tutmak doğruydu.", "gain", "actual"),
    ],
)
def test_direction_word_against_untriggered_stop(
    changes: dict[str, Any], text: str, outcome: str, best: str
) -> None:
    cf = _cf(**changes)
    assert cf.stop_day is None
    assert cf.stop_loss == cf.actual
    out = write_lesson(
        FakeClient(reply(text, outcome=outcome, best=best)), cf, assets=ASSETS, max_retries=0
    )
    assert not out.accepted
    assert out.reason is not None
    assert "yön" in out.reason


def test_right_direction_with_untriggered_stop_is_accepted() -> None:
    text = "ASSET_A pozisyonu %3 kaybettirdi; girmemek en iyisiydi."
    out = write_lesson(
        FakeClient(reply(text, outcome="loss", best="skip")),
        _cf(**UNTRIGGERED_LOSS),
        assets=ASSETS,
        max_retries=0,
    )
    assert out.accepted, out.reason


def test_values_are_checked_as_the_prompt_shows_them() -> None:
    # Raw 3.2549 / 1.1151 are shown as 3.25 / 1.12; "%3,2" and the shown difference "%2,13"
    # are correct readings of the prompt (raw values would reject both).
    cf = _cf(actual=0.032549, half=0.011151, stop_loss=0.032549)
    client = FakeClient(
        reply(
            "ASSET_A %3,2 kazandırdı; yarım boyut %2,13 daha az getirirdi.",
            outcome="gain",
            best="actual",
        )
    )
    out = write_lesson(client, cf, assets=ASSETS, max_retries=0)
    payload = json.loads(client.messages[0][1]["content"])
    assert payload["returns_pct"]["actual"] == 3.25
    assert payload["returns_pct"]["half"] == 1.12
    assert out.accepted, out.reason


@pytest.mark.parametrize(
    ("text", "accepted"),
    [
        ("ASSET_A %4 kazandırdı; -%5 zarar-kes eşiği hiç çalışmadı.", True),
        ("ASSET_A %4 kazandırdı; +%5 zarar-kes eşiği hiç çalışmadı.", False),
    ],
)
def test_threshold_may_be_written_negative_only(text: str, *, accepted: bool) -> None:
    out = write_lesson(
        FakeClient(reply(text, outcome="gain", best="actual")), _cf(), assets=ASSETS, max_retries=0
    )
    assert out.accepted is accepted, out.reason


@pytest.mark.parametrize(
    "name", ["btc", "BTCUSDT", "bitcoinde", "Ether", "eth/usdt", "SOL", "Solana'da", "XRP'ye"]
)
def test_real_names_in_any_form_are_rejected(name: str) -> None:
    text = f"{name} gibi ASSET_B pozisyonu %10 kaybettirdi; girmemek en iyisiydi."
    out = write_lesson(FakeClient(reply(text)), CF, assets=ASSETS, max_retries=0)
    assert out.reason is not None
    assert "gerçek" in out.reason


def test_accepted_result_carries_prompt_version() -> None:
    out = write_lesson(FakeClient(reply()), CF, assets=ASSETS, max_retries=0)
    assert out.accepted
    assert out.prompt_version == "postmortem-v1"


# Follow-up review: false rejections and acceptances of the consistency check.
STOPPED = date(2025, 3, 3)


@pytest.mark.parametrize(
    ("cf", "text", "outcome", "best"),
    [
        # The direction word belongs to the neighbouring clause (cut at "ama", "çünkü").
        (
            _cf(stop_loss=-0.052, stop_day=STOPPED),
            "Zarar-kes %5,2 kaybettirirdi ama ASSET_A tutulunca %4 getirdi.",
            "gain",
            "actual",
        ),
        (CF, "Girmemek kazandırırdı çünkü ASSET_B %10 değer yitirdi.", "loss", "skip"),
        # "zarar kes" written without the hyphen is the stop-loss, not a loss word.
        (_cf(), "zarar kes çalışmadan ASSET_A pozisyonu %4 getirdi.", "gain", "actual"),
        # Equal magnitude, opposite sign: -4 % is another reading of "%4", not the same number.
        (
            _cf(stop_loss=-0.04, stop_day=STOPPED),
            "ASSET_A %4 kazandırdı; zarar-kes erken çalışsa %4 kaybettirirdi.",
            "gain",
            "actual",
        ),
        # |actual| == threshold: "%5" may be the threshold, so its direction is not judged.
        (
            _cf(actual=0.05, half=0.025, stop_loss=0.05),
            "ASSET_A %5 kazandırdı; %5 kayıpta devreye girecek zarar-kes hiç çalışmadı.",
            "gain",
            "actual",
        ),
    ],
)
def test_correct_lessons_are_not_rejected(
    cf: Counterfactual, text: str, outcome: str, best: str
) -> None:
    out = write_lesson(
        FakeClient(reply(text, outcome=outcome, best=best)), cf, assets=ASSETS, max_retries=0
    )
    assert out.accepted, out.reason


def test_negative_threshold_needs_stop_loss_wording() -> None:
    out = write_lesson(
        FakeClient(
            reply("ASSET_A %4 kazandırdı ama -%5 ile kapandı.", outcome="gain", best="actual")
        ),
        _cf(),
        assets=ASSETS,
        max_retries=0,
    )
    assert out.reason is not None
    assert "uyuşmuyor" in out.reason


def test_uppercase_turkish_loss_word_is_caught() -> None:
    out = write_lesson(
        FakeClient(
            reply(
                "ASSET_A pozisyonu %4 KAYIP verdi; tutmak doğruydu.", outcome="gain", best="actual"
            )
        ),
        _cf(),
        assets=ASSETS,
        max_retries=0,
    )
    assert out.reason is not None
    assert "yön" in out.reason


@pytest.mark.parametrize(
    "name",
    [
        "btcde",
        "xrpnin",
        "solusdt",
        "sol/usdt",
        "btc_usdt",
        "SOL'de",
        *(a.value.lower() for a in Asset if a is not Asset.SOL),
    ],
)
def test_more_real_name_forms_are_rejected(name: str) -> None:
    text = f"{name} gibi ASSET_B pozisyonu %10 kaybettirdi; girmemek en iyisiydi."
    out = write_lesson(FakeClient(reply(text)), CF, assets=ASSETS, max_retries=0)
    assert out.reason is not None
    assert "gerçek" in out.reason


@pytest.mark.parametrize("word", ["sol", "solda", "soldaki", "solunda"])
def test_turkish_sol_is_not_a_ticker(word: str) -> None:
    text = f"ASSET_B {word} kanatta %10 kaybettirdi; girmemek en iyisiydi."
    out = write_lesson(FakeClient(reply(text)), CF, assets=ASSETS, max_retries=0)
    assert out.accepted, out.reason


def test_one_lost_attempt_marks_the_result_as_outage_dependent() -> None:
    """A healthy server would have answered the attempt that timed out, so the outcome (a
    rejected lesson, or an accepted one) is not reproducible: the runner must stop the run."""
    timeout = LLMUnavailableError("timeout")
    bad = reply("ASSET_B %99,99 kazandırdı; devam.", outcome="gain")
    partial = write_lesson(FakeClient(bad, timeout, timeout), CF, assets=ASSETS, max_retries=2)
    assert not partial.accepted
    assert partial.llm_unavailable
    late = write_lesson(FakeClient(timeout, reply()), CF, assets=ASSETS, max_retries=2)
    assert late.accepted
    assert late.llm_unavailable
    healthy = write_lesson(FakeClient(bad, reply()), CF, assets=ASSETS, max_retries=2)
    assert healthy.accepted
    assert not healthy.llm_unavailable
