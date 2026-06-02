"""capacités génériques : colonne JSONB au lieu de colonnes par capacité

Revision ID: 0002_capabilities_jsonb
Revises: 0001_initial
Create Date: 2026-06-02

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_capabilities_jsonb"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("model_checks", sa.Column("capabilities", postgresql.JSONB(), nullable=True))
    op.drop_column("model_checks", "tool_calling_status")
    op.drop_column("model_checks", "reasoning_status")
    # Le type enum n'est plus référencé (seul liveness_status subsiste).
    op.execute("DROP TYPE IF EXISTS capability_status")


def downgrade() -> None:
    capability_status = postgresql.ENUM(
        "AVAILABLE", "UNAVAILABLE", "ERROR", "SKIPPED", name="capability_status"
    )
    capability_status.create(op.get_bind(), checkfirst=True)
    enum = postgresql.ENUM(name="capability_status", create_type=False)
    op.add_column(
        "model_checks",
        sa.Column("tool_calling_status", enum, nullable=False, server_default="SKIPPED"),
    )
    op.add_column(
        "model_checks",
        sa.Column("reasoning_status", enum, nullable=False, server_default="SKIPPED"),
    )
    op.alter_column("model_checks", "tool_calling_status", server_default=None)
    op.alter_column("model_checks", "reasoning_status", server_default=None)
    op.drop_column("model_checks", "capabilities")
