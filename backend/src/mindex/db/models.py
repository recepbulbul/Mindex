"""SQLAlchemy 2 ORM models: the executable form of docs/db/schema.sql (Alembic owns the DDL).

Differences from the reference DDL, all deliberate:
- `agents.slug`: the stable id the API and `BaseAgent.agent_id` use (`buy-hold-btc`).
- `experiments.checkpoint`: the simulator's `SimState` JSON, so a run resumes bit for bit (NF2).
"""

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pgvector.sqlalchemy import Vector  # pyright: ignore[reportMissingTypeStubs]
from sqlalchemy import (
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, CITEXT, JSONB, TSVECTOR, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

EMBEDDING_DIM = 1024  # Qwen3-Embedding-0.6B


class UserRole(enum.StrEnum):
    RESEARCHER = "researcher"
    VIEWER = "viewer"


class ExperimentMode(enum.StrEnum):
    REPLAY = "replay"
    LIVE = "live"


class Condition(enum.StrEnum):
    C0 = "C0"
    C1 = "C1"
    C1_NO_REGIME = "C1_NO_REGIME"
    C2 = "C2"
    C3 = "C3"


class ExperimentStatus(enum.StrEnum):
    DRAFT = "draft"
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


class AgentKindDb(enum.StrEnum):
    RULE = "rule"
    RL = "rl"
    LLM = "llm"
    EXTERNAL = "external"


class Regime(enum.StrEnum):
    BULL = "bull"
    BEAR = "bear"
    SIDEWAYS = "sideways"


class TradeSide(enum.StrEnum):
    BUY = "buy"
    SELL = "sell"


class Stance(enum.StrEnum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


def _values(members: type[enum.StrEnum]) -> list[str]:
    return [m.value for m in members]


def _enum(cls: type[enum.StrEnum], name: str) -> Enum:
    # Store the values ("researcher"), not the member names ("RESEARCHER").
    return Enum(cls, name=name, values_callable=_values)


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )


class Base(DeclarativeBase):
    type_annotation_map = {  # noqa: RUF012 (SQLAlchemy reads this class attribute)
        dict[str, Any]: JSONB,
        datetime: DateTime(timezone=True),
        date: Date,
        str: Text,
    }


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _uuid_pk()
    email: Mapped[str] = mapped_column(CITEXT, unique=True)
    password_hash: Mapped[str]
    role: Mapped[UserRole] = mapped_column(
        _enum(UserRole, "user_role"), server_default=UserRole.VIEWER.value
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class AssetRow(Base):
    __tablename__ = "assets"
    __table_args__ = (CheckConstraint("symbol ~ '^[A-Z]{2,10}$'", name="symbol_format"),)

    symbol: Mapped[str] = mapped_column(primary_key=True)
    quote: Mapped[str] = mapped_column(server_default="USDT")


class Experiment(Base):
    __tablename__ = "experiments"
    __table_args__ = (
        CheckConstraint("length(name) BETWEEN 3 AND 120", name="name_length"),
        CheckConstraint("cardinality(assets) > 0", name="assets_nonempty"),
        CheckConstraint("commission_rate BETWEEN 0 AND 0.01", name="commission_range"),
        CheckConstraint("slippage_bps BETWEEN 0 AND 100", name="slippage_range"),
        CheckConstraint("end_date IS NULL OR end_date > start_date", name="period_order"),
        Index("experiments_owner_idx", "owner_id"),
        Index("experiments_status_idx", "status"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    name: Mapped[str]
    mode: Mapped[ExperimentMode] = mapped_column(_enum(ExperimentMode, "experiment_mode"))
    condition: Mapped[Condition] = mapped_column(_enum(Condition, "experiment_condition"))
    status: Mapped[ExperimentStatus] = mapped_column(
        _enum(ExperimentStatus, "experiment_status"),
        server_default=ExperimentStatus.DRAFT.value,
    )
    start_date: Mapped[date]
    end_date: Mapped[date | None]
    assets: Mapped[list[str]] = mapped_column(ARRAY(Text))
    seed: Mapped[int] = mapped_column(Integer)
    commission_rate: Mapped[Decimal] = mapped_column(Numeric(6, 5), server_default=text("0.001"))
    slippage_bps: Mapped[Decimal] = mapped_column(Numeric(6, 2), server_default=text("5"))
    config: Mapped[dict[str, Any]]
    model_version: Mapped[str]
    prompt_version: Mapped[str]
    last_checkpoint_day: Mapped[date | None]
    checkpoint: Mapped[dict[str, Any] | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    agents: Mapped[list["ExperimentAgent"]] = relationship(
        back_populates="experiment", cascade="all, delete-orphan", passive_deletes=True
    )


class AgentRow(Base):
    __tablename__ = "agents"

    id: Mapped[uuid.UUID] = _uuid_pk()
    slug: Mapped[str] = mapped_column(unique=True)
    name: Mapped[str] = mapped_column(unique=True)
    kind: Mapped[AgentKindDb] = mapped_column(_enum(AgentKindDb, "agent_kind"))
    persona: Mapped[str | None]
    params: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))


class ExperimentAgent(Base):
    __tablename__ = "experiment_agents"
    __table_args__ = (
        UniqueConstraint("experiment_id", "agent_id"),
        CheckConstraint("initial_cash > 0", name="initial_cash_positive"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    experiment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("experiments.id", ondelete="CASCADE")
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id", ondelete="RESTRICT"))
    initial_cash: Mapped[Decimal] = mapped_column(Numeric(20, 2), server_default=text("10000"))

    experiment: Mapped[Experiment] = relationship(back_populates="agents")
    agent: Mapped[AgentRow] = relationship(lazy="joined")


class DecisionRow(Base):
    __tablename__ = "decisions"
    __table_args__ = (
        UniqueConstraint("experiment_agent_id", "day"),
        CheckConstraint("confidence BETWEEN 0 AND 1", name="confidence_range"),
        CheckConstraint("attempts BETWEEN 1 AND 3", name="attempts_range"),
        CheckConstraint("latency_ms >= 0", name="latency_nonnegative"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    experiment_agent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("experiment_agents.id", ondelete="CASCADE")
    )
    day: Mapped[date]
    target_weights: Mapped[dict[str, Any]]
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    rationale: Mapped[str | None]
    regime: Mapped[Regime | None] = mapped_column(_enum(Regime, "market_regime"))
    attempts: Mapped[int] = mapped_column(SmallInteger, server_default=text("1"))
    held_position: Mapped[bool] = mapped_column(server_default=text("false"))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    trace_id: Mapped[str | None]


class TradeRow(Base):
    __tablename__ = "trades"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("price > 0", name="price_positive"),
        CheckConstraint("fee >= 0", name="fee_nonnegative"),
        Index("trades_decision_idx", "decision_id"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    decision_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("decisions.id", ondelete="CASCADE"))
    asset: Mapped[str] = mapped_column(ForeignKey("assets.symbol"))
    side: Mapped[TradeSide] = mapped_column(_enum(TradeSide, "trade_side"))
    quantity: Mapped[Decimal] = mapped_column(Numeric(28, 10))
    price: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    fee: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    executed_at: Mapped[datetime]


class PortfolioSnapshot(Base):
    __tablename__ = "portfolio_snapshots"
    __table_args__ = (
        CheckConstraint("equity >= 0", name="equity_nonnegative"),
        CheckConstraint("cash >= 0", name="cash_nonnegative"),
    )

    experiment_agent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("experiment_agents.id", ondelete="CASCADE"), primary_key=True
    )
    day: Mapped[date] = mapped_column(primary_key=True)
    equity: Mapped[Decimal] = mapped_column(Numeric(20, 2))
    cash: Mapped[Decimal] = mapped_column(Numeric(20, 2))
    holdings: Mapped[dict[str, Any]]


class MemoryRow(Base):
    __tablename__ = "memories"
    __table_args__ = (
        CheckConstraint("length(lesson) BETWEEN 20 AND 2000", name="lesson_length"),
        CheckConstraint("importance BETWEEN 0 AND 1", name="importance_range"),
        Index(
            "memories_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index("memories_tsv_gin", "lesson_tsv", postgresql_using="gin"),
        Index("memories_owner_regime", "experiment_agent_id", "regime"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    experiment_agent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("experiment_agents.id", ondelete="CASCADE")
    )
    source_trade_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("trades.id", ondelete="SET NULL")
    )
    day: Mapped[date]  # the day the lesson became known; retrieval only returns earlier days
    lesson: Mapped[str]
    counterfactual: Mapped[dict[str, Any]]
    regime: Mapped[Regime] = mapped_column(_enum(Regime, "market_regime"))
    importance: Mapped[Decimal] = mapped_column(Numeric(3, 2))
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM))
    lesson_tsv: Mapped[str] = mapped_column(
        TSVECTOR, Computed("to_tsvector('simple', lesson)", persisted=True)
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class DecisionMemory(Base):
    __tablename__ = "decision_memories"

    decision_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("decisions.id", ondelete="CASCADE"), primary_key=True
    )
    memory_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("memories.id", ondelete="CASCADE"), primary_key=True
    )
    score: Mapped[Decimal] = mapped_column(Numeric(6, 5))


class ForumMessageRow(Base):
    __tablename__ = "forum_messages"
    __table_args__ = (
        CheckConstraint("length(content) <= 1000", name="content_length"),
        Index("forum_messages_exp_day_idx", "experiment_id", "day"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    experiment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("experiments.id", ondelete="CASCADE")
    )
    sender_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("experiment_agents.id", ondelete="CASCADE")
    )
    day: Mapped[date]
    content: Mapped[str]
    asset: Mapped[str | None] = mapped_column(ForeignKey("assets.symbol"))
    stance: Mapped[Stance] = mapped_column(_enum(Stance, "forum_stance"))
    flagged: Mapped[bool] = mapped_column(server_default=text("false"))
    verified: Mapped[bool | None]


class DecisionForumRead(Base):
    __tablename__ = "decision_forum_reads"
    __table_args__ = (CheckConstraint("weight BETWEEN 0 AND 1", name="weight_range"),)

    decision_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("decisions.id", ondelete="CASCADE"), primary_key=True
    )
    forum_message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("forum_messages.id", ondelete="CASCADE"), primary_key=True
    )
    weight: Mapped[Decimal] = mapped_column(Numeric(5, 4))


class TrustScoreRow(Base):
    __tablename__ = "trust_scores"
    __table_args__ = (
        CheckConstraint("confirmed >= 0", name="confirmed_nonnegative"),
        CheckConstraint("refuted >= 0", name="refuted_nonnegative"),
        CheckConstraint("truster_id <> trustee_id", name="no_self_trust"),
    )

    truster_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("experiment_agents.id", ondelete="CASCADE"), primary_key=True
    )
    trustee_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("experiment_agents.id", ondelete="CASCADE"), primary_key=True
    )
    confirmed: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    refuted: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    score: Mapped[Decimal] = mapped_column(
        Numeric(5, 4),
        Computed("(confirmed + 1)::numeric / (confirmed + refuted + 2)", persisted=True),
    )
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())
