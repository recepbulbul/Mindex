"""Lesson writing from a counterfactual table, with a numeric consistency check (P5).

Flow: anonymised table -> LLM (JSON schema) -> Pydantic validation -> consistency check
against the table -> retry with the rejection reason (at most `llm_max_retries`) -> either
`MemoryStore.add` (day = closing day) or a rejection with its reason; nothing is written then.

The prompt shows only percentages, the anonymised asset code and a holding length in days:
no price level or calendar date that could identify the asset or the period. Lessons are
stored with the `ASSET_x` code, and a lesson that names a real symbol is rejected, so a
lesson cannot leak a name back into a later anonymised decision prompt.
"""

import json
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from itertools import combinations
from typing import Any
from uuid import UUID

import structlog
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from mindex.agents.llm import ChatClient, LLMUnavailableError, anonymise
from mindex.config import get_settings
from mindex.db.models import MemoryRow, Regime
from mindex.domain.decision import Asset
from mindex.memory.store import MemoryStore
from mindex.postmortem.counterfactual import Counterfactual

POSTMORTEM_PROMPT_VERSION = "postmortem-v1"
FLAT_RETURN = 1e-4  # |actual| below 0.01 % counts as flat
CONSISTENCY_TARGET = 0.9

SYSTEM_PROMPT = """You review a closed position of a crypto trading agent in a daily, long-only
simulation. You receive the counterfactual table: the realised return of the position and what
it would have returned if the agent had skipped it, traded half the size, or used a stop-loss.
All returns are percentages of the position's entry cost. Write one short, reusable lesson in
Turkish (1-3 sentences) for the agent's future decisions. Rules:
- Cite at least one number from the table as a percentage (for example %3,2); every
  percentage you write must be a value from the table, the stop-loss threshold, or the
  difference of two table values.
- Use only the anonymised asset code you were given; never name a real coin.
- `outcome` is whether the realised return was a gain, a loss or flat.
- `best_scenario` is the scenario with the highest return in the table.
- `importance` in [0, 1]: how much this lesson should matter later.
- `regime`: the market regime the lesson applies to (bull, bear or sideways)."""

# Tickers case-sensitively (the Turkish word "sol" is not SOL), coin names in any case.
REAL_SYMBOLS = re.compile(
    r"\b(" + "|".join(a.value for a in Asset) + r"|(?i:bitcoin|ethereum|solana|ripple))\b"
)
# Direction words right after a percentage ("%10 kazandırdı"); "zarar-kes" is not a loss word.
GAIN_STEMS = ("kazan", "kâr", "yüksel")
LOSS_STEMS = ("kayb", "kayıp", "zarar", "düş", "geriled")
CLAUSE_END = re.compile(r"[.;,:]")
DIRECTION_WINDOW = 40
# `%5,2`, `% 5`, `-%3`, `%-3`, `+%2`, `5.2%`, `4 %`, `yüzde 5`; Turkish and English decimals.
# The minus may also be the Unicode minus sign (U+2212).
MINUS = "-" + chr(0x2212)
_NUM = r"(\d+(?:[.,]\d+)?)"
_SIGN = f"([{MINUS}+])?"
PERCENT = re.compile(
    rf"{_SIGN}%\s?{_SIGN}{_NUM}|{_SIGN}{_NUM}\s?%|yüzde\s+{_SIGN}{_NUM}", re.IGNORECASE
)

log = structlog.get_logger(__name__)


class Outcome(StrEnum):
    GAIN = "gain"
    LOSS = "loss"
    FLAT = "flat"


class Scenario(StrEnum):
    ACTUAL = "actual"
    SKIP = "skip"
    HALF = "half"
    STOP_LOSS = "stop_loss"


class LessonDraft(BaseModel):
    """LLM output; the length and importance bounds mirror the `memories` CHECK constraints."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    lesson: str = Field(min_length=20, max_length=2000)
    importance: float = Field(ge=0.0, le=1.0)
    regime: Regime
    outcome: Outcome
    best_scenario: Scenario


def lesson_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["lesson", "importance", "regime", "outcome", "best_scenario"],
        "properties": {
            "lesson": {"type": "string", "minLength": 20, "maxLength": 2000},
            "importance": {"type": "number", "minimum": 0, "maximum": 1},
            "regime": {"type": "string", "enum": [r.value for r in Regime]},
            "outcome": {"type": "string", "enum": [o.value for o in Outcome]},
            "best_scenario": {"type": "string", "enum": [s.value for s in Scenario]},
        },
    }


def build_messages(
    cf: Counterfactual, code: str, regime_hint: Regime | None
) -> list[dict[str, str]]:
    user = {
        "asset": code,
        "holding_days": cf.holding_days,
        "stop_loss_threshold_pct": round(cf.stop_pct * 100, 2),
        "stop_loss_triggered": cf.stop_day is not None,
        "returns_pct": {k: round(v * 100, 2) for k, v in cf.table().items()},
        "regime_label": None if regime_hint is None else regime_hint.value,
    }
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(user, separators=(",", ":"))},
    ]


@dataclass(frozen=True, slots=True)
class PercentClaim:
    value: float  # in percent, as written (magnitude when `signed` is False)
    decimals: int
    signed: bool  # an explicit sign (+ or -) was written
    end: int  # offset just after the match in the text


def percent_claims(text: str) -> list[PercentClaim]:
    claims: list[PercentClaim] = []
    for m in PERCENT.finditer(text):
        groups = m.groups()
        number = next(g for g in (groups[2], groups[4], groups[6]) if g is not None)
        signs = [g for g in (groups[0], groups[1], groups[3], groups[5]) if g is not None]
        negative = any(g in MINUS for g in signs)
        parts = re.split(r"[.,]", number)
        decimals = len(parts[1]) if len(parts) > 1 else 0
        magnitude = float(number.replace(",", "."))
        claims.append(
            PercentClaim(-magnitude if negative else magnitude, decimals, bool(signs), m.end())
        )
    return claims


def _matches(claim: PercentClaim, value: float, *, signed_allowed: bool) -> bool:
    """`value` (percent) written at the claim's precision equals the claim."""
    half_step = 0.5 * 10**-claim.decimals + 1e-9
    if claim.signed:
        return signed_allowed and abs(value - claim.value) <= half_step
    return abs(abs(value) - claim.value) <= half_step


def outcome_of(cf: Counterfactual) -> Outcome:
    if cf.actual > FLAT_RETURN:
        return Outcome.GAIN
    if cf.actual < -FLAT_RETURN:
        return Outcome.LOSS
    return Outcome.FLAT


def best_scenarios(cf: Counterfactual) -> set[Scenario]:
    table = cf.table()
    top = max(table.values())
    return {Scenario(k) for k, v in table.items() if math.isclose(v, top, abs_tol=1e-6)}


def check_consistency(draft: LessonDraft, cf: Counterfactual) -> str | None:
    """None if the lesson agrees with the table, otherwise the reason (Turkish, for the retry).

    Every %-marked number in the lesson text must be a table value, the stop-loss threshold or
    the difference of two table values, rounded to the precision it was written with; an
    explicit sign (+ or -) must match a table value's sign. A lesson with no percentage fails:
    an unfalsifiable lesson would inflate the consistency rate. `outcome` and `best_scenario`
    must match the realised direction and the best scenario. A percentage that can only be the
    realised return must not be followed, in its clause, by a word of the opposite direction
    ("%10 kazandırdı" for a loss); other wording is checked only through signs and `outcome`.
    """
    if REAL_SYMBOLS.search(draft.lesson):
        return "ders gerçek bir varlık adı içeriyor; yalnızca verilen kodu kullan"
    pct = {k: v * 100 for k, v in cf.table().items()}
    differences = [a - b for a, b in combinations(pct.values(), 2)]
    claims = percent_claims(draft.lesson)
    if not claims:
        return "derste tablodan hiçbir yüzde değeri yok"
    for claim in claims:
        if not (
            any(_matches(claim, v, signed_allowed=True) for v in pct.values())
            or _matches(claim, cf.stop_pct * 100, signed_allowed=False)
            or any(_matches(claim, d, signed_allowed=False) for d in differences)
        ):
            return f"%{claim.value:g} değeri tabloyla uyuşmuyor"
        if _contradicts_direction(draft.lesson, claim, cf, pct, differences):
            return f"%{claim.value:g} gerçekleşen getirinin yönüyle çelişiyor"
    expected = outcome_of(cf)
    if draft.outcome is not expected:
        return f"sonuç yönü yanlış: gerçekleşen getiri {expected.value}"
    best = best_scenarios(cf)
    if draft.best_scenario not in best:
        return f"en iyi senaryo yanlış: {', '.join(sorted(s.value for s in best))}"
    return None


def _contradicts_direction(
    text: str,
    claim: PercentClaim,
    cf: Counterfactual,
    pct: dict[str, float],
    differences: list[float],
) -> bool:
    """An unsigned percentage that can only be the realised return, followed in its clause by
    a gain word when the position lost (or a loss word when it gained)."""
    if claim.signed or cf.actual == 0 or not _matches(claim, pct["actual"], signed_allowed=True):
        return False
    # actual - skip is the actual return itself (skip = 0), not another reading of the number
    diffs = [d for d in differences if not math.isclose(abs(d), abs(pct["actual"]))]
    others = [v for k, v in pct.items() if k != "actual"] + [cf.stop_pct * 100, *diffs]
    if any(_matches(claim, v, signed_allowed=False) for v in others):
        return False  # ambiguous: the number may describe another scenario
    clause = CLAUSE_END.split(text[claim.end : claim.end + DIRECTION_WINDOW], maxsplit=1)[0]
    clause = clause.lower().replace("zarar-kes", "")
    gain = any(stem in clause for stem in GAIN_STEMS)
    loss = any(stem in clause for stem in LOSS_STEMS)
    return (gain and not loss) if cf.actual < 0 else (loss and not gain)


@dataclass(frozen=True, slots=True)
class Attempt:
    schema_valid: bool  # the output parsed and passed `LessonDraft` validation
    consistent: bool
    reason: str | None


@dataclass(frozen=True, slots=True)
class PostmortemResult:
    draft: LessonDraft | None
    attempts: tuple[Attempt, ...]

    @property
    def accepted(self) -> bool:
        return self.draft is not None

    @property
    def reason(self) -> str | None:
        """Why the lesson was rejected (last attempt's reason); None when accepted."""
        return None if self.accepted else self.attempts[-1].reason


def write_lesson(
    client: ChatClient,
    cf: Counterfactual,
    *,
    assets: Sequence[Asset],
    regime_hint: Regime | None = None,
    max_retries: int | None = None,
) -> PostmortemResult:
    """Ask for a lesson until one passes `check_consistency` or `max_retries` run out."""
    retries = get_settings().llm_max_retries if max_retries is None else max_retries
    code = anonymise(tuple(assets))[cf.asset]
    messages = build_messages(cf, code, regime_hint)
    schema = lesson_schema()
    attempts: list[Attempt] = []
    for _ in range(retries + 1):
        try:
            raw = client.complete(messages, schema=schema)
        except LLMUnavailableError as exc:
            attempts.append(Attempt(False, False, f"LLM erişilemedi: {exc}"))
            continue
        try:
            draft = LessonDraft.model_validate_json(raw)
        except ValidationError as exc:
            attempts.append(Attempt(False, False, f"geçersiz JSON/şema ({exc.error_count()} hata)"))
            continue
        reason = check_consistency(draft, cf)
        attempts.append(Attempt(True, reason is None, reason))
        if reason is None:
            return _logged(PostmortemResult(draft, tuple(attempts)), cf)
        messages = [
            *messages,
            {"role": "assistant", "content": raw},
            {"role": "user", "content": f"Ders reddedildi: {reason}. Tabloya uygun yeniden yaz."},
        ]
    return _logged(PostmortemResult(None, tuple(attempts)), cf)


def _logged(result: PostmortemResult, cf: Counterfactual) -> PostmortemResult:
    log.info(
        "postmortem_lesson",
        prompt_version=POSTMORTEM_PROMPT_VERSION,
        exit_day=cf.exit_day.isoformat(),
        attempts=len(result.attempts),
        accepted=result.accepted,
        reason=result.reason,
    )
    return result


def save_lesson(
    store: MemoryStore,
    experiment_agent_id: UUID,
    cf: Counterfactual,
    draft: LessonDraft,
    *,
    source_trade_id: UUID | None = None,
) -> MemoryRow:
    """Stage an accepted lesson; `day` is the closing day (usable from the next day on)."""
    return store.add(
        experiment_agent_id,
        cf.exit_day,
        draft.lesson,
        cf.table(),
        draft.regime,
        draft.importance,
        source_trade_id,
    )


def postmortem(
    client: ChatClient,
    store: MemoryStore,
    experiment_agent_id: UUID,
    cf: Counterfactual,
    *,
    assets: Sequence[Asset],
    regime_hint: Regime | None = None,
    max_retries: int | None = None,
    source_trade_id: UUID | None = None,
) -> tuple[PostmortemResult, MemoryRow | None]:
    """Write a lesson and store it if it passes the check; a rejected lesson is not stored."""
    result = write_lesson(
        client,
        cf,
        assets=assets,
        regime_hint=regime_hint,
        max_retries=max_retries,
    )
    if result.draft is None:
        return result, None
    return result, save_lesson(
        store, experiment_agent_id, cf, result.draft, source_trade_id=source_trade_id
    )


def consistency_rate(results: Sequence[PostmortemResult]) -> float | None:
    """Share of schema-valid generated lessons (every attempt, before any filtering) that
    passed the check; None if there were none. Target: >= `CONSISTENCY_TARGET`.

    Measured before rejection on purpose: stored lessons are consistent by construction.
    """
    valid = [a for r in results for a in r.attempts if a.schema_valid]
    if not valid:
        return None
    return sum(a.consistent for a in valid) / len(valid)
