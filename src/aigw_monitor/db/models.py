"""Modèles ORM (time-series des checks)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from ..checks.result import LivenessStatus
from .base import Base

# JSONB sur PostgreSQL, JSON générique ailleurs (tests sqlite).
JSON_VARIANT = JSON().with_variant(JSONB(), "postgresql")

# Type enum nommé pour le statut liveness (réutilisé).
_liveness_enum = SAEnum(LivenessStatus, name="liveness_status", validate_strings=True)


class CheckRun(Base):
    """Un cycle de scheduler."""

    __tablename__ = "check_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    trigger: Mapped[str] = mapped_column(String(20), default="scheduled", nullable=False)
    total_targets: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    up_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    checks: Mapped[list[ModelCheck]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class ModelCheck(Base):
    """Résultat des sondes pour un (organisation, modèle) lors d'un cycle."""

    __tablename__ = "model_checks"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("check_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization: Mapped[str] = mapped_column(String(255), nullable=False)
    base_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    liveness_status: Mapped[LivenessStatus] = mapped_column(_liveness_enum, nullable=False)
    latency_ms: Mapped[float | None] = mapped_column(Float)
    # Map générique {nom_capacité: {status, latency_ms, http_status, error, details}}.
    capabilities: Mapped[dict | None] = mapped_column(JSON_VARIANT)

    http_status: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict | None] = mapped_column(JSON_VARIANT)

    run: Mapped[CheckRun] = relationship(back_populates="checks")

    __table_args__ = (
        Index("ix_model_checks_org_model_checked", "organization", "model", "checked_at"),
    )
