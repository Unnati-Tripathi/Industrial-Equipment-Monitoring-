"""
alembic/env.py

Async Alembic migration environment for Northstar.

Key differences from the default template:
- Uses asyncio.run() + AsyncEngine so migrations work with asyncpg.
- DATABASE_URL is read from the app Settings object (same source as the app).
- All ORM models are imported so autogenerate can detect schema changes.
- The sync fallback (run_migrations_offline) generates SQL without a live DB,
  useful for producing a migration script for review before applying.
"""
from __future__ import annotations

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# ── Import all ORM models so Alembic sees the full metadata ──────────────────
# Even though we only reference Base.metadata, the model classes must be
# imported so their Table objects register themselves on the metadata object.
from app.db.base import Base  # noqa: F401
import app.db.models  # noqa: F401  triggers all mapper registrations

from app.config import get_settings

# ── Alembic config ────────────────────────────────────────────────────────────
alembic_cfg = context.config

if alembic_cfg.config_file_name is not None:
    fileConfig(alembic_cfg.config_file_name)

# Override the URL from alembic.ini with the value from our settings object.
# This means there is exactly one source of truth for the database URL.
settings = get_settings()
alembic_cfg.set_main_option("sqlalchemy.url", settings.database_url)

target_metadata = Base.metadata


# ── Offline mode ──────────────────────────────────────────────────────────────

def run_migrations_offline() -> None:
    """Generate migration SQL without connecting to the database."""
    url = alembic_cfg.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


# ── Online mode (async) ───────────────────────────────────────────────────────

def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,      # detect column type changes in autogenerate
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    engine = async_engine_from_config(
        alembic_cfg.get_section(alembic_cfg.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,   # no pooling for migration runs
    )
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


# ── Entry point ───────────────────────────────────────────────────────────────
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
