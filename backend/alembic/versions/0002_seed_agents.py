"""Seed the agent catalogue with the ids the frontend uses (`frontend/src/mocks/fixtures.ts`).

`params` tells the experiment runner how to build each agent: the rule agent's class and
settings, or the LLM persona key of `mindex.agents.llm.PERSONAS`.

Downgrade removes the seeded agents together with every experiment link to them
(`experiment_agents`, and through its cascades the runs' decisions, trades, snapshots and
memories); the experiments themselves stay, without those agents.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

AGENTS: list[dict[str, object]] = [
    {
        "slug": "buy-hold-btc",
        "name": "Al-ve-tut BTC",
        "kind": "rule",
        "persona": None,
        "params": {"rule": "buy_and_hold", "asset": "BTC"},
    },
    {
        "slug": "equal-weight",
        "name": "Eşit ağırlık",
        "kind": "rule",
        "persona": None,
        "params": {"rule": "equal_weight", "rebalance_days": 30},
    },
    {
        "slug": "ma-cross",
        "name": "MA kesişimi (10/30)",
        "kind": "rule",
        "persona": None,
        "params": {"rule": "ma_cross", "short": 10, "long": 30},
    },
    {"slug": "ppo", "name": "PPO", "kind": "rl", "persona": None, "params": {}},
    {
        "slug": "llm-momentum",
        "name": "LLM · Momentum",
        "kind": "llm",
        "persona": "Trendi takip eder; güçlenen varlıklara ağırlık verir.",
        "params": {"persona": "momentum"},
    },
    {
        "slug": "llm-mean-reversion",
        "name": "LLM · Ortalamaya dönüş",
        "kind": "llm",
        "persona": "Sert düşüşlerden sonra tepki alımı arar.",
        "params": {"persona": "mean-reversion"},
    },
    {
        "slug": "llm-sentiment",
        "name": "LLM · Duyarlılık",
        "kind": "llm",
        "persona": "Fear & Greed ve funding oranına göre pozisyon alır.",
        "params": {"persona": "sentiment"},
    },
    {
        "slug": "llm-risk-averse",
        "name": "LLM · Riskten kaçınan",
        "kind": "llm",
        "persona": "Sermayeyi korumayı önceler; ayı rejiminde nakde geçer.",
        "params": {"persona": "risk-averse"},
    },
    {
        "slug": "mcp-guest",
        "name": "MCP misafir ajanı",
        "kind": "external",
        "persona": "MCP sunucusu üzerinden katılan dış LLM ajanı.",
        "params": {},
    },
]


def upgrade() -> None:
    agents = sa.table(
        "agents",
        sa.column("slug", sa.Text()),
        sa.column("name", sa.Text()),
        sa.column("kind", postgresql.ENUM(name="agent_kind", create_type=False)),
        sa.column("persona", sa.Text()),
        sa.column("params", postgresql.JSONB()),
    )
    op.bulk_insert(agents, AGENTS)


def downgrade() -> None:
    slugs = [str(a["slug"]) for a in AGENTS]
    # `experiment_agents.agent_id` is ON DELETE RESTRICT: drop the links first.
    op.execute(
        sa.text(
            "DELETE FROM experiment_agents WHERE agent_id IN "
            "(SELECT id FROM agents WHERE slug = ANY(:slugs))"
        ).bindparams(slugs=slugs)
    )
    op.execute(sa.text("DELETE FROM agents WHERE slug = ANY(:slugs)").bindparams(slugs=slugs))
