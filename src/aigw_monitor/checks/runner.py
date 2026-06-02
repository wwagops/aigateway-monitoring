"""Orchestration d'un cycle de checks : cibles → sondes (concurrence) → persistance + métriques."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol

from ..config.loader import ResolvedTarget
from ..logging import get_logger
from ..settings import Settings
from .capabilities import CAPABILITY_NAMES, CAPABILITY_PROBES, selected_probes, unsupported_enabled
from .client import OpenAICompatClient
from .probes import check_liveness
from .result import CapabilityStatus, LivenessStatus, ProbeResult

if TYPE_CHECKING:  # éviter une dépendance dure à l'import
    from sqlalchemy.ext.asyncio import async_sessionmaker

log = get_logger(__name__)


@dataclass
class ModelCheckResult:
    organization: str
    base_url: str
    model: str
    liveness: ProbeResult
    # Résultat par capacité (clé = nom du registre) ; générique, extensible sans changer ce type.
    capabilities: dict[str, ProbeResult] = field(default_factory=dict)
    mismatches: list[str] = field(default_factory=list)

    @property
    def is_up(self) -> bool:
        return self.liveness.status == LivenessStatus.UP

    @property
    def has_error(self) -> bool:
        if self.liveness.status == LivenessStatus.ERROR:
            return True
        return any(r.status == CapabilityStatus.ERROR for r in self.capabilities.values())


@dataclass
class RunSummary:
    started_at: datetime
    finished_at: datetime
    total: int
    up: int
    errors: int
    results: list[ModelCheckResult]
    run_id: int | None = None

    @property
    def duration_seconds(self) -> float:
        return (self.finished_at - self.started_at).total_seconds()


class MetricsSink(Protocol):
    def record(self, summary: RunSummary) -> None: ...


def _detect_mismatches(
    target: ResolvedTarget, capabilities: dict[str, ProbeResult]
) -> list[str]:
    """Capacité déclarée ``true`` mais sonde ``UNAVAILABLE`` → dérive."""
    mismatches: list[str] = []
    for name, result in capabilities.items():
        spec = target.capabilities.get(name)
        if spec is not None and spec.enabled and result.status == CapabilityStatus.UNAVAILABLE:
            mismatches.append(name)
    return mismatches


async def _check_target(
    target: ResolvedTarget, settings: Settings, semaphore: asyncio.Semaphore
) -> ModelCheckResult:
    probes = selected_probes(target)
    capabilities: dict[str, ProbeResult] = {}
    async with semaphore:
        async with OpenAICompatClient(
            target.base_url, target.api_key, settings.http_timeout_seconds
        ) as client:
            liveness = await check_liveness(client, target)
            for name in CAPABILITY_NAMES:
                if name in probes:
                    capabilities[name] = await CAPABILITY_PROBES[name](client, target)
                else:
                    capabilities[name] = ProbeResult.skipped(CapabilityStatus)

    for name in unsupported_enabled(target):
        log.warning(
            "capacité activée sans sonde enregistrée (ignorée)",
            organization=target.organization,
            model=target.model,
            capability=name,
        )

    mismatches = _detect_mismatches(target, capabilities)
    if mismatches:
        log.warning(
            "dérive de capacité détectée",
            organization=target.organization,
            model=target.model,
            mismatches=mismatches,
        )
    return ModelCheckResult(
        organization=target.organization,
        base_url=target.base_url,
        model=target.model,
        liveness=liveness,
        capabilities=capabilities,
        mismatches=mismatches,
    )


async def run_cycle(
    *,
    targets: list[ResolvedTarget],
    settings: Settings,
    session_factory: async_sessionmaker | None = None,
    metrics: MetricsSink | None = None,
    trigger: str = "scheduled",
) -> RunSummary:
    """Exécute un cycle complet de checks sur toutes les cibles."""
    started_at = datetime.now(UTC)
    semaphore = asyncio.Semaphore(settings.max_concurrency)
    results = list(
        await asyncio.gather(*(_check_target(t, settings, semaphore) for t in targets))
    )
    finished_at = datetime.now(UTC)

    summary = RunSummary(
        started_at=started_at,
        finished_at=finished_at,
        total=len(results),
        up=sum(1 for r in results if r.is_up),
        errors=sum(1 for r in results if r.has_error),
        results=results,
    )

    if session_factory is not None:
        from ..db.repository import save_run

        async with session_factory() as session:
            run = await save_run(
                session,
                started_at=started_at,
                finished_at=finished_at,
                trigger=trigger,
                results=results,
            )
            summary.run_id = run.id

    if metrics is not None:
        metrics.record(summary)

    log.info(
        "cycle terminé",
        run_id=summary.run_id,
        total=summary.total,
        up=summary.up,
        errors=summary.errors,
        duration_s=round(summary.duration_seconds, 3),
    )
    return summary
