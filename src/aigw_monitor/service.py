"""Daemon : serveur HTTP (API REST + /metrics) + scheduler interne, même boucle asyncio."""

from __future__ import annotations

import uvicorn
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .api import create_app
from .checks.runner import run_cycle
from .config.loader import load_config
from .db.base import create_all_if_sqlite, make_engine, make_session_factory
from .logging import configure_logging, get_logger
from .metrics import PrometheusMetrics
from .scheduler import build_trigger
from .settings import Settings

log = get_logger(__name__)


async def run_service(settings: Settings) -> None:
    configure_logging(settings.log_level)
    config = load_config(settings.config_path)
    log.info(
        "configuration chargée",
        organizations=len(config.organizations),
        targets=len(config.targets),
    )

    engine = make_engine(settings.database_url)
    if await create_all_if_sqlite(engine):
        log.info("schéma SQLite local initialisé (pas de migration Alembic requise)")
    session_factory = make_session_factory(engine)
    metrics = PrometheusMetrics()
    app = create_app(settings, session_factory, config, metrics=metrics)

    scheduler = AsyncIOScheduler()

    async def job() -> None:
        try:
            await run_cycle(
                targets=config.targets,
                settings=settings,
                session_factory=session_factory,
                metrics=metrics,
                trigger="scheduled",
            )
        except Exception:
            log.exception("échec du cycle de check")

    scheduler.add_job(
        job, build_trigger(settings.schedule), id="check-cycle", max_instances=1, coalesce=True
    )

    # Cycle initial avant de servir.
    await job()
    scheduler.start()

    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host=settings.api_host,
            port=settings.api_port,
            log_config=None,
            lifespan="on",
        )
    )
    log.info(
        "serveur démarré",
        host=settings.api_host,
        port=settings.api_port,
        metrics_path=settings.metrics_path,
    )
    try:
        await server.serve()
    finally:
        scheduler.shutdown(wait=False)
        await engine.dispose()
        log.info("arrêt propre")
