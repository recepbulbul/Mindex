"""Initial schema: the executable form of docs/db/schema.sql.

Deviations from the reference DDL: `agents.slug` (stable API id), `experiments.checkpoint`
(SimState JSON for resumable runs), `memories.day` (when a lesson became known; retrieval
only returns earlier lessons, so no look-ahead). Prices stay in Parquet snapshots, so there is
no `prices` table yet. Constraint names follow `mindex.db.models.NAMING_CONVENTION`.

Revision ID: 0001
Revises:
Create Date: 2026-11-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ENUMS: dict[str, tuple[str, ...]] = {
    "user_role": ("researcher", "viewer"),
    "experiment_mode": ("replay", "live"),
    "experiment_condition": ("C0", "C1", "C1_NO_REGIME", "C2", "C3"),
    "experiment_status": ("draft", "queued", "running", "paused", "completed", "failed"),
    "agent_kind": ("rule", "rl", "llm", "external"),
    "market_regime": ("bull", "bear", "sideways"),
    "trade_side": ("buy", "sell"),
    "forum_stance": ("bullish", "bearish", "neutral"),
}
ASSETS = ("BTC", "ETH", "SOL", "BNB", "XRP")


def upgrade() -> None:
    for ext in ("vector", "citext", "pgcrypto"):
        op.execute(f"CREATE EXTENSION IF NOT EXISTS {ext}")
    for name, values in ENUMS.items():
        postgresql.ENUM(*values, name=name).create(op.get_bind())
    op.create_table(
        "agents",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("kind", postgresql.ENUM(name="agent_kind", create_type=False), nullable=False),
        sa.Column("persona", sa.Text(), nullable=True),
        sa.Column(
            "params",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agents")),
        sa.UniqueConstraint("name", name=op.f("uq_agents_name")),
        sa.UniqueConstraint("slug", name=op.f("uq_agents_slug")),
    )
    op.create_table(
        "assets",
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("quote", sa.Text(), server_default="USDT", nullable=False),
        sa.CheckConstraint("symbol ~ '^[A-Z]{2,10}$'", name=op.f("ck_assets_symbol_format")),
        sa.PrimaryKeyConstraint("symbol", name=op.f("pk_assets")),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("email", postgresql.CITEXT(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column(
            "role",
            postgresql.ENUM(name="user_role", create_type=False),
            server_default="viewer",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    op.create_table(
        "experiments",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "mode", postgresql.ENUM(name="experiment_mode", create_type=False), nullable=False
        ),
        sa.Column(
            "condition",
            postgresql.ENUM(name="experiment_condition", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "status",
            postgresql.ENUM(name="experiment_status", create_type=False),
            server_default="draft",
            nullable=False,
        ),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("assets", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.Column(
            "commission_rate",
            sa.Numeric(precision=6, scale=5),
            server_default=sa.text("0.001"),
            nullable=False,
        ),
        sa.Column(
            "slippage_bps",
            sa.Numeric(precision=6, scale=2),
            server_default=sa.text("5"),
            nullable=False,
        ),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("model_version", sa.Text(), nullable=False),
        sa.Column("prompt_version", sa.Text(), nullable=False),
        sa.Column("last_checkpoint_day", sa.Date(), nullable=True),
        sa.Column("checkpoint", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("cardinality(assets) > 0", name=op.f("ck_experiments_assets_nonempty")),
        sa.CheckConstraint(
            "commission_rate BETWEEN 0 AND 0.01", name=op.f("ck_experiments_commission_range")
        ),
        sa.CheckConstraint(
            "end_date IS NULL OR end_date > start_date", name=op.f("ck_experiments_period_order")
        ),
        sa.CheckConstraint(
            "length(name) BETWEEN 3 AND 120", name=op.f("ck_experiments_name_length")
        ),
        sa.CheckConstraint(
            "slippage_bps BETWEEN 0 AND 100", name=op.f("ck_experiments_slippage_range")
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
            name=op.f("fk_experiments_owner_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_experiments")),
    )
    op.create_index("experiments_owner_idx", "experiments", ["owner_id"], unique=False)
    op.create_index("experiments_status_idx", "experiments", ["status"], unique=False)
    op.create_table(
        "experiment_agents",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("experiment_id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column(
            "initial_cash",
            sa.Numeric(precision=20, scale=2),
            server_default=sa.text("10000"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "initial_cash > 0", name=op.f("ck_experiment_agents_initial_cash_positive")
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name=op.f("fk_experiment_agents_agent_id_agents"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["experiment_id"],
            ["experiments.id"],
            name=op.f("fk_experiment_agents_experiment_id_experiments"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_experiment_agents")),
        sa.UniqueConstraint(
            "experiment_id", "agent_id", name=op.f("uq_experiment_agents_experiment_id")
        ),
    )
    op.create_table(
        "decisions",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("experiment_agent_id", sa.UUID(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("target_weights", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("confidence", sa.Numeric(precision=4, scale=3), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column(
            "regime", postgresql.ENUM(name="market_regime", create_type=False), nullable=True
        ),
        sa.Column("attempts", sa.SmallInteger(), server_default=sa.text("1"), nullable=False),
        sa.Column("held_position", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("trace_id", sa.Text(), nullable=True),
        sa.CheckConstraint("attempts BETWEEN 1 AND 3", name=op.f("ck_decisions_attempts_range")),
        sa.CheckConstraint(
            "confidence BETWEEN 0 AND 1", name=op.f("ck_decisions_confidence_range")
        ),
        sa.CheckConstraint("latency_ms >= 0", name=op.f("ck_decisions_latency_nonnegative")),
        sa.ForeignKeyConstraint(
            ["experiment_agent_id"],
            ["experiment_agents.id"],
            name=op.f("fk_decisions_experiment_agent_id_experiment_agents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_decisions")),
        sa.UniqueConstraint(
            "experiment_agent_id", "day", name=op.f("uq_decisions_experiment_agent_id")
        ),
    )
    op.create_table(
        "forum_messages",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("experiment_id", sa.UUID(), nullable=False),
        sa.Column("sender_id", sa.UUID(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("asset", sa.Text(), nullable=True),
        sa.Column(
            "stance", postgresql.ENUM(name="forum_stance", create_type=False), nullable=False
        ),
        sa.Column("flagged", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=True),
        sa.CheckConstraint(
            "length(content) <= 1000", name=op.f("ck_forum_messages_content_length")
        ),
        sa.ForeignKeyConstraint(
            ["asset"], ["assets.symbol"], name=op.f("fk_forum_messages_asset_assets")
        ),
        sa.ForeignKeyConstraint(
            ["experiment_id"],
            ["experiments.id"],
            name=op.f("fk_forum_messages_experiment_id_experiments"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["sender_id"],
            ["experiment_agents.id"],
            name=op.f("fk_forum_messages_sender_id_experiment_agents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_forum_messages")),
    )
    op.create_index(
        "forum_messages_exp_day_idx", "forum_messages", ["experiment_id", "day"], unique=False
    )
    op.create_table(
        "portfolio_snapshots",
        sa.Column("experiment_agent_id", sa.UUID(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("equity", sa.Numeric(precision=20, scale=2), nullable=False),
        sa.Column("cash", sa.Numeric(precision=20, scale=2), nullable=False),
        sa.Column("holdings", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint("cash >= 0", name=op.f("ck_portfolio_snapshots_cash_nonnegative")),
        sa.CheckConstraint("equity >= 0", name=op.f("ck_portfolio_snapshots_equity_nonnegative")),
        sa.ForeignKeyConstraint(
            ["experiment_agent_id"],
            ["experiment_agents.id"],
            name=op.f("fk_portfolio_snapshots_experiment_agent_id_experiment_agents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("experiment_agent_id", "day", name=op.f("pk_portfolio_snapshots")),
    )
    op.create_table(
        "trust_scores",
        sa.Column("truster_id", sa.UUID(), nullable=False),
        sa.Column("trustee_id", sa.UUID(), nullable=False),
        sa.Column("confirmed", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("refuted", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "score",
            sa.Numeric(precision=5, scale=4),
            sa.Computed("(confirmed + 1)::numeric / (confirmed + refuted + 2)", persisted=True),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("confirmed >= 0", name=op.f("ck_trust_scores_confirmed_nonnegative")),
        sa.CheckConstraint("refuted >= 0", name=op.f("ck_trust_scores_refuted_nonnegative")),
        sa.CheckConstraint("truster_id <> trustee_id", name=op.f("ck_trust_scores_no_self_trust")),
        sa.ForeignKeyConstraint(
            ["trustee_id"],
            ["experiment_agents.id"],
            name=op.f("fk_trust_scores_trustee_id_experiment_agents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["truster_id"],
            ["experiment_agents.id"],
            name=op.f("fk_trust_scores_truster_id_experiment_agents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("truster_id", "trustee_id", name=op.f("pk_trust_scores")),
    )
    op.create_table(
        "decision_forum_reads",
        sa.Column("decision_id", sa.UUID(), nullable=False),
        sa.Column("forum_message_id", sa.UUID(), nullable=False),
        sa.Column("weight", sa.Numeric(precision=5, scale=4), nullable=False),
        sa.CheckConstraint(
            "weight BETWEEN 0 AND 1", name=op.f("ck_decision_forum_reads_weight_range")
        ),
        sa.ForeignKeyConstraint(
            ["decision_id"],
            ["decisions.id"],
            name=op.f("fk_decision_forum_reads_decision_id_decisions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["forum_message_id"],
            ["forum_messages.id"],
            name=op.f("fk_decision_forum_reads_forum_message_id_forum_messages"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "decision_id", "forum_message_id", name=op.f("pk_decision_forum_reads")
        ),
    )
    op.create_table(
        "trades",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("decision_id", sa.UUID(), nullable=False),
        sa.Column("asset", sa.Text(), nullable=False),
        sa.Column("side", postgresql.ENUM(name="trade_side", create_type=False), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=28, scale=10), nullable=False),
        sa.Column("price", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("fee", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("fee >= 0", name=op.f("ck_trades_fee_nonnegative")),
        sa.CheckConstraint("price > 0", name=op.f("ck_trades_price_positive")),
        sa.CheckConstraint("quantity > 0", name=op.f("ck_trades_quantity_positive")),
        sa.ForeignKeyConstraint(["asset"], ["assets.symbol"], name=op.f("fk_trades_asset_assets")),
        sa.ForeignKeyConstraint(
            ["decision_id"],
            ["decisions.id"],
            name=op.f("fk_trades_decision_id_decisions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_trades")),
    )
    op.create_index("trades_decision_idx", "trades", ["decision_id"], unique=False)
    op.create_table(
        "memories",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("experiment_agent_id", sa.UUID(), nullable=False),
        sa.Column("source_trade_id", sa.UUID(), nullable=True),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("lesson", sa.Text(), nullable=False),
        sa.Column("counterfactual", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "regime", postgresql.ENUM(name="market_regime", create_type=False), nullable=False
        ),
        sa.Column("importance", sa.Numeric(precision=3, scale=2), nullable=False),
        sa.Column("embedding", Vector(1024), nullable=False),
        sa.Column(
            "lesson_tsv",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('simple', lesson)", persisted=True),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("importance BETWEEN 0 AND 1", name=op.f("ck_memories_importance_range")),
        sa.CheckConstraint(
            "length(lesson) BETWEEN 20 AND 2000", name=op.f("ck_memories_lesson_length")
        ),
        sa.ForeignKeyConstraint(
            ["experiment_agent_id"],
            ["experiment_agents.id"],
            name=op.f("fk_memories_experiment_agent_id_experiment_agents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_trade_id"],
            ["trades.id"],
            name=op.f("fk_memories_source_trade_id_trades"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_memories")),
    )
    op.create_index(
        "memories_embedding_hnsw",
        "memories",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index(
        "memories_owner_regime", "memories", ["experiment_agent_id", "regime"], unique=False
    )
    op.create_index(
        "memories_tsv_gin", "memories", ["lesson_tsv"], unique=False, postgresql_using="gin"
    )
    op.create_table(
        "decision_memories",
        sa.Column("decision_id", sa.UUID(), nullable=False),
        sa.Column("memory_id", sa.UUID(), nullable=False),
        sa.Column("score", sa.Numeric(precision=6, scale=5), nullable=False),
        sa.ForeignKeyConstraint(
            ["decision_id"],
            ["decisions.id"],
            name=op.f("fk_decision_memories_decision_id_decisions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["memory_id"],
            ["memories.id"],
            name=op.f("fk_decision_memories_memory_id_memories"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("decision_id", "memory_id", name=op.f("pk_decision_memories")),
    )
    assets = sa.table("assets", sa.column("symbol", sa.Text()))
    op.bulk_insert(assets, [{"symbol": a} for a in ASSETS])


def downgrade() -> None:
    op.drop_table("decision_memories")
    op.drop_index("memories_tsv_gin", table_name="memories", postgresql_using="gin")
    op.drop_index("memories_owner_regime", table_name="memories")
    op.drop_index(
        "memories_embedding_hnsw",
        table_name="memories",
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.drop_table("memories")
    op.drop_index("trades_decision_idx", table_name="trades")
    op.drop_table("trades")
    op.drop_table("decision_forum_reads")
    op.drop_table("trust_scores")
    op.drop_table("portfolio_snapshots")
    op.drop_index("forum_messages_exp_day_idx", table_name="forum_messages")
    op.drop_table("forum_messages")
    op.drop_table("decisions")
    op.drop_table("experiment_agents")
    op.drop_index("experiments_status_idx", table_name="experiments")
    op.drop_index("experiments_owner_idx", table_name="experiments")
    op.drop_table("experiments")
    op.drop_table("users")
    op.drop_table("assets")
    op.drop_table("agents")
    for name in reversed(ENUMS):
        postgresql.ENUM(name=name).drop(op.get_bind())
