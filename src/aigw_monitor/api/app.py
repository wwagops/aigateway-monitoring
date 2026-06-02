"""Fabrique de l'application FastAPI (API REST + montage /metrics)."""

from __future__ import annotations

from fastapi import FastAPI
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.requests import Request
from starlette.responses import Response

from ..config.loader import LoadedConfig
from ..metrics import PrometheusMetrics
from ..settings import Settings
from .routes import router


def create_app(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    config: LoadedConfig,
    metrics: PrometheusMetrics | None = None,
) -> FastAPI:
    app = FastAPI(
        title="aigw-monitor",
        version="0.1.0",
        description="Consultation de l'état des modèles surveillés (up, tool calling, reasoning).",
    )
    app.state.settings = settings
    app.state.session_factory = session_factory
    app.state.config = config

    app.include_router(router)

    if metrics is not None:
        # Route explicite (et non app.mount) pour servir le chemin exact en 200,
        # sans redirection 307 vers une variante avec slash final.
        async def metrics_endpoint(_: Request) -> Response:
            return Response(generate_latest(metrics.registry), media_type=CONTENT_TYPE_LATEST)

        app.add_route(settings.metrics_path, metrics_endpoint, methods=["GET"])

    return app
