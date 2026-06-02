"""Endpoints REST (lecture seule)."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..checks.capabilities import selected_probes
from ..config.loader import LoadedConfig
from ..db import repository
from ..settings import Settings
from .deps import get_config, get_session, get_settings
from .schemas import (
    HealthOut,
    ModelStatusOut,
    OrganizationOut,
    RunDetailOut,
    RunOut,
    TargetOut,
)

router = APIRouter()


@router.get("/health", response_model=HealthOut, tags=["meta"])
async def health(
    session: AsyncSession = Depends(get_session),
    config: LoadedConfig = Depends(get_config),
) -> HealthOut:
    db_status = "ok"
    last_run_id: int | None = None
    try:
        await session.execute(text("SELECT 1"))
        last_run_id = await repository.latest_completed_run_id(session)
    except Exception:  # pragma: no cover - dépend de la DB
        db_status = "error"
    return HealthOut(
        status="ok" if db_status == "ok" else "degraded",
        database=db_status,
        targets=len(config.targets),
        last_run_id=last_run_id,
    )


@router.get("/api/organizations", response_model=list[OrganizationOut], tags=["config"])
async def list_organizations(
    config: LoadedConfig = Depends(get_config),
    settings: Settings = Depends(get_settings),
) -> list[OrganizationOut]:
    return [
        OrganizationOut(
            name=org.name,
            base_url=org.base_url if settings.expose_base_url else None,
            models=org.models,
        )
        for org in config.organizations
    ]


@router.get("/api/models", response_model=list[TargetOut], tags=["config"])
async def list_models(
    config: LoadedConfig = Depends(get_config),
    settings: Settings = Depends(get_settings),
) -> list[TargetOut]:
    return [
        TargetOut(
            organization=t.organization,
            model=t.model,
            base_url=t.base_url if settings.expose_base_url else None,
            capabilities=t.enabled_capabilities,
            probes=selected_probes(t),
        )
        for t in config.targets
    ]


@router.get("/api/status", response_model=list[ModelStatusOut], tags=["status"])
async def current_status(
    org: str | None = Query(default=None),
    model: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> list[ModelStatusOut]:
    rows = await repository.get_current_status(session, organization=org, model=model)
    return [ModelStatusOut.from_orm_check(mc, settings.expose_base_url) for mc in rows]


@router.get(
    "/api/models/{org}/{model}/history",
    response_model=list[ModelStatusOut],
    tags=["status"],
)
async def model_history(
    org: str,
    model: str,
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> list[ModelStatusOut]:
    rows = await repository.get_history(
        session, organization=org, model=model, since=since, until=until, limit=limit
    )
    return [ModelStatusOut.from_orm_check(mc, settings.expose_base_url) for mc in rows]


@router.get("/api/runs", response_model=list[RunOut], tags=["runs"])
async def list_runs(
    limit: int = Query(default=50, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
) -> list[RunOut]:
    runs = await repository.list_runs(session, limit=limit)
    return [RunOut.from_orm_run(r) for r in runs]


@router.get("/api/runs/{run_id}", response_model=RunDetailOut, tags=["runs"])
async def get_run(
    run_id: int,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> RunDetailOut:
    run = await repository.get_run(session, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run introuvable")
    detail = RunDetailOut.from_orm_run(run)
    detail.checks = [
        ModelStatusOut.from_orm_check(mc, settings.expose_base_url) for mc in run.checks
    ]
    return detail
