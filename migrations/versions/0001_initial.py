"""schéma initial : check_runs + model_checks

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-01

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

liveness_status = postgresql.ENUM(
    "UP", "DOWN", "ERROR", "SKIPPED", name="liveness_status"
)
capability_status = postgresql.ENUM(
    "AVAILABLE", "UNAVAILABLE", "ERROR", "SKIPPED", name="capability_status"
)


def upgrade() -> None:
    bind = op.get_bind()
    liveness_status.create(bind, checkfirst=True)
    capability_status.create(bind, checkfirst=True)

    op.create_table(
        "check_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trigger", sa.String(length=20), nullable=False, server_default="scheduled"),
        sa.Column("total_targets", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("up_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_count", sa.Integer(), nullable=False, server_default="0"),
    )

    op.create_table(
        "model_checks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "run_id",
            sa.Integer(),
            sa.ForeignKey("check_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("organization", sa.String(length=255), nullable=False),
        sa.Column("base_url", sa.String(length=1024), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "liveness_status",
            postgresql.ENUM(name="liveness_status", create_type=False),
            nullable=False,
        ),
        sa.Column("latency_ms", sa.Float(), nullable=True),
        sa.Column(
            "tool_calling_status",
            postgresql.ENUM(name="capability_status", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "reasoning_status",
            postgresql.ENUM(name="capability_status", create_type=False),
            nullable=False,
        ),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("details", postgresql.JSONB(), nullable=True),
    )
    op.create_index("ix_model_checks_run_id", "model_checks", ["run_id"])
    op.create_index(
        "ix_model_checks_org_model_checked",
        "model_checks",
        ["organization", "model", "checked_at"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    op.drop_index("ix_model_checks_org_model_checked", table_name="model_checks")
    op.drop_index("ix_model_checks_run_id", table_name="model_checks")
    op.drop_table("model_checks")
    op.drop_table("check_runs")
    capability_status.drop(bind, checkfirst=True)
    liveness_status.drop(bind, checkfirst=True)
