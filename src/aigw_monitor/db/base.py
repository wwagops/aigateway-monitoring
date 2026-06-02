"""Moteur async, fabrique de sessions et Base déclarative."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


def make_engine(database_url: str, echo: bool = False) -> AsyncEngine:
    return create_async_engine(database_url, echo=echo, pool_pre_ping=True)


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def create_all_if_sqlite(engine: AsyncEngine) -> bool:
    """Crée le schéma via les métadonnées **uniquement sur SQLite**.

    Les migrations Alembic sont spécifiques à PostgreSQL (types enum natifs, JSONB) ; sur
    SQLite (défaut local) on initialise donc le schéma directement. Sur tout autre dialecte
    on ne fait rien (le schéma est géré par Alembic). Retourne True si le schéma a été créé.
    """
    if engine.dialect.name != "sqlite":
        return False
    from . import models  # noqa: F401  (enregistre les tables sur Base.metadata)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return True
