"""Forum: the day advice was judged (`forum_messages.verified_on`).

Trust counts (`trust_scores`) hold only the current state; with the verdict day the API can
replay how trust evolved (`TrustHistoryPoint`) without a separate history table.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("forum_messages", sa.Column("verified_on", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("forum_messages", "verified_on")
