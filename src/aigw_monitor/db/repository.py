"""Persistance d'un cycle et requêtes de lecture pour l'API."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .models import CheckRun, ModelCheck

if TYPE_CHECKING:
    from ..checks.runner import ModelCheckResult


def _probe_to_dict(probe: Any) -> dict[str, Any]:
    return {
        "status": probe.status.value,
        "latency_ms": probe.latency_ms,
        "http_status": probe.http_status,
        "error": probe.error,
        "request": probe.request,
        "details": probe.details,
    }


async def save_run(
    session: AsyncSession,
    *,
    started_at: datetime,
    finished_at: datetime,
    trigger: str,
    results: list[ModelCheckResult],
) -> CheckRun:
    run = CheckRun(
        started_at=started_at,
        finished_at=finished_at,
        trigger=trigger,
        total_targets=len(results),
        up_count=sum(1 for r in results if r.is_up),
        error_count=sum(1 for r in results if r.has_error),
    )
    session.add(run)
    await session.flush()  # obtenir run.id

    for r in results:
        session.add(
            ModelCheck(
                run_id=run.id,
                organization=r.organization,
                base_url=r.base_url,
                model=r.model,
                checked_at=finished_at,
                liveness_status=r.liveness.status,
                latency_ms=r.liveness.latency_ms,
                capabilities={
                    name: _probe_to_dict(res) for name, res in r.capabilities.items()
                },
                http_status=r.liveness.http_status,
                error=r.liveness.error,
                details={
                    "mismatches": r.mismatches,
                    "liveness_probe": r.liveness_name,
                    "liveness": _probe_to_dict(r.liveness),
                },
            )
        )
    await session.commit()
    return run


async def latest_completed_run_id(session: AsyncSession) -> int | None:
    stmt = (
        select(CheckRun.id)
        .where(CheckRun.finished_at.is_not(None))
        .order_by(CheckRun.id.desc())
        .limit(1)
    )
    return await session.scalar(stmt)


async def get_current_status(
    session: AsyncSession,
    organization: str | None = None,
    model: str | None = None,
) -> list[ModelCheck]:
    """État courant = lignes du dernier cycle terminé (chaque cycle couvre toutes les cibles)."""
    run_id = await latest_completed_run_id(session)
    if run_id is None:
        return []
    stmt = select(ModelCheck).where(ModelCheck.run_id == run_id)
    if organization is not None:
        stmt = stmt.where(ModelCheck.organization == organization)
    if model is not None:
        stmt = stmt.where(ModelCheck.model == model)
    stmt = stmt.order_by(ModelCheck.organization, ModelCheck.model)
    return list((await session.scalars(stmt)).all())


async def get_history(
    session: AsyncSession,
    organization: str,
    model: str,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 100,
) -> list[ModelCheck]:
    stmt = select(ModelCheck).where(
        ModelCheck.organization == organization, ModelCheck.model == model
    )
    if since is not None:
        stmt = stmt.where(ModelCheck.checked_at >= since)
    if until is not None:
        stmt = stmt.where(ModelCheck.checked_at <= until)
    stmt = stmt.order_by(ModelCheck.checked_at.desc()).limit(limit)
    return list((await session.scalars(stmt)).all())


async def list_runs(session: AsyncSession, limit: int = 50) -> list[CheckRun]:
    stmt = select(CheckRun).order_by(CheckRun.id.desc()).limit(limit)
    return list((await session.scalars(stmt)).all())


async def get_run(session: AsyncSession, run_id: int) -> CheckRun | None:
    stmt = (
        select(CheckRun)
        .where(CheckRun.id == run_id)
        .options(selectinload(CheckRun.checks))
    )
    return await session.scalar(stmt)
