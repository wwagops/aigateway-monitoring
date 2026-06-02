"""Schémas de réponse de l'API (lecture seule, données de monitoring uniquement)."""

from __future__ import annotations

from datetime import datetime
from typing import Self

from pydantic import BaseModel

from ..db.models import CheckRun, ModelCheck


class OrganizationOut(BaseModel):
    name: str
    base_url: str | None = None
    models: list[str]


class TargetOut(BaseModel):
    organization: str
    model: str
    base_url: str | None = None
    capabilities: list[str]
    probes: list[str]


class ModelStatusOut(BaseModel):
    organization: str
    model: str
    base_url: str | None = None
    run_id: int
    checked_at: datetime
    liveness_status: str
    latency_ms: float | None = None
    # Map générique {nom_capacité: statut} (ex. {"tool_calling": "AVAILABLE", ...}).
    capabilities: dict[str, str] = {}
    http_status: int | None = None
    error: str | None = None
    mismatches: list[str] = []

    @classmethod
    def from_orm_check(cls, mc: ModelCheck, expose_base_url: bool) -> Self:
        details = mc.details or {}
        capabilities = {
            name: entry.get("status", "")
            for name, entry in (mc.capabilities or {}).items()
        }
        return cls(
            organization=mc.organization,
            model=mc.model,
            base_url=mc.base_url if expose_base_url else None,
            run_id=mc.run_id,
            checked_at=mc.checked_at,
            liveness_status=mc.liveness_status.value,
            latency_ms=mc.latency_ms,
            capabilities=capabilities,
            http_status=mc.http_status,
            error=mc.error,
            mismatches=list(details.get("mismatches") or []),
        )


class RunOut(BaseModel):
    id: int
    started_at: datetime
    finished_at: datetime | None = None
    trigger: str
    total_targets: int
    up_count: int
    error_count: int

    @classmethod
    def from_orm_run(cls, run: CheckRun) -> Self:
        return cls(
            id=run.id,
            started_at=run.started_at,
            finished_at=run.finished_at,
            trigger=run.trigger,
            total_targets=run.total_targets,
            up_count=run.up_count,
            error_count=run.error_count,
        )


class RunDetailOut(RunOut):
    checks: list[ModelStatusOut] = []


class HealthOut(BaseModel):
    status: str
    database: str
    targets: int
    last_run_id: int | None = None
