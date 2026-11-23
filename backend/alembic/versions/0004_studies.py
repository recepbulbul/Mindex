"""Studies: condition x seed groups of experiments for the C0-C3 comparison (#54).

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "studies",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("length(name) BETWEEN 3 AND 80", name=op.f("ck_studies_name_length")),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name=op.f("fk_studies_owner_id_users"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_studies")),
    )
    op.add_column("experiments", sa.Column("study_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("fk_experiments_study_id_studies"),
        "experiments",
        "studies",
        ["study_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("experiments_study_idx", "experiments", ["study_id"])


def downgrade() -> None:
    op.drop_index("experiments_study_idx", table_name="experiments")
    op.drop_constraint(op.f("fk_experiments_study_id_studies"), "experiments", type_="foreignkey")
    op.drop_column("experiments", "study_id")
    op.drop_table("studies")
