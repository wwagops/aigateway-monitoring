"""Tests de l'init SQLite automatique."""

from __future__ import annotations

from sqlalchemy import inspect

from aigw_monitor.db.base import create_all_if_sqlite, make_engine


async def test_create_all_if_sqlite_creates_schema(tmp_path):
    db = tmp_path / "x.db"
    engine = make_engine(f"sqlite+aiosqlite:///{db}")
    try:
        created = await create_all_if_sqlite(engine)
        assert created is True

        async with engine.connect() as conn:
            tables = await conn.run_sync(lambda c: inspect(c).get_table_names())
        assert {"check_runs", "model_checks"} <= set(tables)

        # idempotent (create_all ne recrée pas les tables existantes)
        assert await create_all_if_sqlite(engine) is True
    finally:
        await engine.dispose()
