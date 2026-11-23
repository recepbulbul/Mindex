"""Base for API schemas: camelCase on the wire (frontend/src/api/types.ts), snake_case in Python."""

import math
import re
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    EmailStr,
    Field,
    StrictStr,
    field_validator,
)
from pydantic.alias_generators import to_camel

from mindex.db.models import (
    AgentKindDb,
    Condition,
    ExperimentMode,
    ExperimentStatus,
    TradeSide,
    UserRole,
)
from mindex.domain.decision import Asset
from mindex.domain.forum import Stance
from mindex.domain.regime import Regime


class ApiModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
        extra="forbid",
    )


class ApiErrorBody(ApiModel):
    """Every error response: `{detail, fields?}` (frontend `ApiErrorBody`)."""

    detail: str
    fields: dict[str, str] | None = None


class Health(ApiModel):
    status: Literal["ok", "degraded"]
    database: bool


# ---------------------------------------------------------------- auth (F1)

Email = Annotated[EmailStr, AfterValidator(lambda e: e.lower())]
# Upper bound keeps one request from making Argon2 hash megabytes (cheap DoS).
Password = Annotated[str, Field(min_length=8, max_length=128)]


class LoginRequest(ApiModel):
    email: Email
    password: str = Field(min_length=1, max_length=128)


class RegisterRequest(ApiModel):
    email: Email
    password: Password


class UserOut(ApiModel):
    email: str
    role: UserRole


class LoginResponse(ApiModel):
    token: str
    user: UserOut


# ---------------------------------------------------------------- experiments (F2)
# The rules mirror `experimentCreateSchema` in frontend/src/lib/schemas.ts, messages included;
# cross-field rules, known agents and the sealed test window are checked in
# `mindex.api.routers.experiments.check_config` (they need the whole configuration).

SEED_MAX = 2**31 - 1


def _iso_date(value: object) -> object:
    """`YYYY-MM-DD` strings (JSON) or `date` objects (YAML's `safe_load`); nothing else."""
    if value is None or (isinstance(value, date) and not isinstance(value, datetime)):
        return value
    if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    raise ValueError("Tarih YYYY-AA-GG olmalı")


def _number(value: object) -> object:
    # Like `z.number()`: no strings or booleans coerced into numbers.
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError("Sayı olmalı")
    try:
        finite = math.isfinite(value)
    except OverflowError:  # an integer with hundreds of digits does not fit a float
        raise ValueError("Sayı çok büyük") from None
    if not finite:
        raise ValueError("Sayı olmalı")
    return value


def _integer(value: object) -> object:
    # Like `z.number().int()`: 5 and 5.0 are the same JS number, "5" is not a number.
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("Tam sayı olmalı")
    return value


IsoDate = Annotated[date, BeforeValidator(_iso_date)]
Number = Annotated[float, BeforeValidator(_number)]


class ExperimentCreate(ApiModel):
    name: str
    mode: ExperimentMode
    condition: Condition
    start_date: IsoDate
    end_date: IsoDate | None
    assets: list[Asset]
    agent_ids: list[StrictStr]
    seed: Annotated[int, BeforeValidator(_integer)]
    commission_rate: Number
    slippage_bps: Number

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if chr(0) in v:  # PostgreSQL text cannot store NUL
            raise ValueError("Geçersiz karakter içeriyor")
        if len(v) < 3:
            raise ValueError("En az 3 karakter")
        if len(v) > 120:
            raise ValueError("En fazla 120 karakter")
        return v

    @field_validator("assets")
    @classmethod
    def _assets(cls, v: list[Asset]) -> list[Asset]:
        if not v:
            raise ValueError("En az bir varlık seçin")
        return v

    @field_validator("agent_ids")
    @classmethod
    def _agents(cls, v: list[str]) -> list[str]:
        if len(v) < 2:
            raise ValueError("En az iki ajan seçin")
        return v

    @field_validator("seed")
    @classmethod
    def _seed(cls, v: int) -> int:
        if not 0 <= v <= SEED_MAX:
            raise ValueError(f"0 ile {SEED_MAX} arasında olmalı")
        return v

    @field_validator("commission_rate")
    @classmethod
    def _commission(cls, v: float) -> float:
        if v < 0:
            raise ValueError("Negatif olamaz")
        if v > 0.01:
            raise ValueError("En fazla %1")
        return v

    @field_validator("slippage_bps")
    @classmethod
    def _slippage(cls, v: float) -> float:
        if v < 0:
            raise ValueError("Negatif olamaz")
        if v > 100:
            raise ValueError("En fazla 100 bp")
        return v


class ExperimentUpdate(ApiModel):
    """PATCH body, for the OpenAPI schema only: the endpoint merges these fields into the
    stored configuration and validates the result as a whole `ExperimentCreate`."""

    name: str | None = None
    mode: ExperimentMode | None = None
    condition: Condition | None = None
    start_date: date | None = None
    end_date: date | None = None
    assets: list[Asset] | None = None
    agent_ids: list[str] | None = None
    seed: int | None = None
    commission_rate: float | None = None
    slippage_bps: float | None = None


class ExperimentOut(ApiModel):
    id: str
    name: str
    mode: ExperimentMode
    condition: Condition
    status: ExperimentStatus
    start_date: date
    end_date: date | None
    assets: list[Asset]
    agent_ids: list[str]
    seed: int
    commission_rate: float
    slippage_bps: float
    model_version: str
    prompt_version: str
    created_at: datetime
    error: str | None = None  # why the last run failed (status "failed"), else null
    study_id: str | None = None  # the study it belongs to, if any


class AgentOut(ApiModel):
    id: str  # the slug
    name: str
    kind: AgentKindDb
    persona: str | None
    available: bool  # false: this server cannot run it (no trained PPO model, MCP)


# ---------------------------------------------------------------- results (F2-F6 read endpoints)


class CandleOut(ApiModel):
    time: date
    open: float
    high: float
    low: float
    close: float
    volume: float


class TradeOut(ApiModel):
    id: str
    agent_id: str
    day: date
    asset: Asset
    side: TradeSide
    quantity: float
    price: float
    fee: float


class EquityPoint(ApiModel):
    day: date
    equity: float


class AgentRun(ApiModel):
    agent: AgentOut
    equity: list[EquityPoint]
    weights: list[dict[Asset, float]]


class TimelineOut(ApiModel):
    experiment_id: str
    days: list[date]
    regimes: list[Regime]
    candles: dict[Asset, list[CandleOut]]
    runs: list[AgentRun]
    trades: list[TradeOut]


class MemoryRef(ApiModel):
    id: str
    score: float


class DecisionOut(ApiModel):
    id: str
    agent_id: str
    day: date
    target_weights: dict[Asset, float]
    confidence: float
    rationale: str
    regime: Regime
    attempts: int
    held_position: bool
    latency_ms: int
    memories: list[MemoryRef]
    forum_message_ids: list[str]


class TrustScoreOut(ApiModel):
    truster_id: str
    trustee_id: str
    confirmed: int
    refuted: int
    score: float


class TrustHistoryPoint(ApiModel):
    day: date
    trustee_id: str
    score: float


class AgentDetailOut(ApiModel):
    agent: AgentOut
    equity: list[EquityPoint]
    decisions: list[DecisionOut]
    trust_given: list[TrustScoreOut]
    trust_received: list[TrustScoreOut]


class AgentMetrics(ApiModel):
    agent_id: str
    total_return: float
    sharpe: float
    max_drawdown: float
    trades: int


class ConditionSummary(ApiModel):
    condition: Condition
    runs: int  # completed runs (seeds) the row is computed from
    complete: bool  # every run of this condition in the study has completed
    sharpe_mean: float
    sharpe_ci_low: float
    sharpe_ci_high: float
    max_drawdown: float
    total_return: float
    herd_correlation: float | None  # None: fewer than two LLM agents in every run
    lesson_consistency: float | None
    mean_forum_weight: float | None  # mean w read (per run, then over runs); None without forum


class ReportOut(ApiModel):
    experiment_id: str
    agents: list[AgentMetrics]
    benchmark: AgentMetrics
    herd_correlation: float | None  # None below two LLM agents
    conditions: list[ConditionSummary]


class CounterfactualOut(ApiModel):
    actual: float
    skip: float
    half: float
    stop_loss: float


class MemoryOut(ApiModel):
    id: str
    agent_id: str
    day: date
    lesson: str
    counterfactual: CounterfactualOut
    regime: Regime
    importance: float


class ForumMessageOut(ApiModel):
    id: str
    sender_id: str
    day: date
    content: str
    asset: Asset
    stance: Stance
    regime: Regime  # the market regime of the day it was posted (filter, #13)
    flagged: bool
    verified: bool | None


class ForumOut(ApiModel):
    messages: list[ForumMessageOut]
    trust: list[TrustScoreOut]
    trust_history: list[TrustHistoryPoint]


# ---------------------------------------------------------------- studies (#54)

SMOKE_DAYS = 14  # `smoke`: this many days from `startDate`, first seed only
MAX_SEEDS = 10


class StudyCreate(ApiModel):
    """Every condition x every seed over one period, agents, assets and costs. Field rules are
    those of `ExperimentCreate`; the period and agents are checked like an experiment's."""

    name: str
    start_date: IsoDate
    end_date: IsoDate
    assets: list[Asset]
    agent_ids: list[StrictStr]
    seeds: list[Annotated[int, BeforeValidator(_integer)]]
    smoke: bool = False
    commission_rate: Number = 0.001
    slippage_bps: Number = 5.0

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = ExperimentCreate._name(v)  # pyright: ignore[reportPrivateUsage]
        if len(v) > 80:
            raise ValueError("En fazla 80 karakter")
        return v

    @field_validator("assets")
    @classmethod
    def _assets(cls, v: list[Asset]) -> list[Asset]:
        if not v:
            raise ValueError("En az bir varlık seçin")
        if len(set(v)) != len(v):
            raise ValueError("Aynı varlık birden fazla seçilmiş")
        return v

    @field_validator("agent_ids")
    @classmethod
    def _agents(cls, v: list[str]) -> list[str]:
        return ExperimentCreate._agents(v)  # pyright: ignore[reportPrivateUsage]

    @field_validator("seeds")
    @classmethod
    def _seeds(cls, v: list[int]) -> list[int]:
        if not 1 <= len(v) <= MAX_SEEDS:
            raise ValueError(f"1 ile {MAX_SEEDS} arasında seed")
        if len(set(v)) != len(v):
            raise ValueError("Seed'ler farklı olmalı")
        for seed in v:
            ExperimentCreate._seed(seed)  # pyright: ignore[reportPrivateUsage]
        return v

    @field_validator("commission_rate")
    @classmethod
    def _commission(cls, v: float) -> float:
        return ExperimentCreate._commission(v)  # pyright: ignore[reportPrivateUsage]

    @field_validator("slippage_bps")
    @classmethod
    def _slippage(cls, v: float) -> float:
        return ExperimentCreate._slippage(v)  # pyright: ignore[reportPrivateUsage]


class StudyRunOut(ApiModel):
    experiment_id: str
    condition: Condition
    seed: int
    status: ExperimentStatus
    last_day: date | None


class StudyOut(ApiModel):
    id: str
    name: str
    start_date: date
    end_date: date
    assets: list[Asset]
    agent_ids: list[str]
    seeds: list[int]
    smoke: bool
    commission_rate: float
    slippage_bps: float
    status: ExperimentStatus
    created_at: datetime
    runs: list[StudyRunOut]


class ConditionDifference(ApiModel):
    """Over the seeds both conditions completed (`seeds`); never mixes unpaired runs."""

    condition: Condition
    baseline: Condition
    seeds: int
    sharpe_diff: float
    ci_low: float
    ci_high: float


class StudyComparisonOut(ApiModel):
    study_id: str
    complete: bool
    days: int
    block_length: int
    resamples: int
    conditions: list[ConditionSummary]
    differences: list[ConditionDifference]
