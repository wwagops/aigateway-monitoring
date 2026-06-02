"""Dépendances FastAPI : settings, config chargée, session de base de données."""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from ..config.loader import LoadedConfig
from ..settings import Settings


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_config(request: Request) -> LoadedConfig:
    return request.app.state.config


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    factory = request.app.state.session_factory
    async with factory() as session:
        yield session
