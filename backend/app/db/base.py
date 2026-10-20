"""
app/db/base.py

Async SQLAlchemy engine, session factory, and declarative base.

Design decisions
────────────────
• async engine via asyncpg (Postgres) or aiosqlite (SQLite for tests/dev).
  The driver is inferred from the DATABASE_URL scheme so switching between them
  requires only an env var change.

• A single `AsyncSessionLocal` factory is the standard entry point.
  FastAPI route dependencies (Phase 4) will use `get_db_session()` as an
  async context manager / dependency.

• `Base` is the declarative base for all ORM models.  Importing it here keeps
  the metadata in one place so Alembic can discover all tables automatically.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

# ── Engine ────────────────────────────────────────────────────────────────────
# echo=False in production; set echo=True temporarily for SQL debugging.
# pool_pre_ping sends a cheap SELECT 1 before each connection is used —
# this recovers gracefully from database restarts without application errors.
def _make_engine(url: str | None = None):
    settings = get_settings()
    db_url = url or settings.database_url
    return create_async_engine(
        db_url,
        echo=False,
        pool_pre_ping=True,
        # Limit pool size to be friendly in dev / CI environments
        pool_size=5,
        max_overflow=10,
    )


# Module-level engine created from settings.  Tests override this by passing
# a custom URL directly to `get_session_factory()`.
_engine = _make_engine()

AsyncSessionLocal = async_sessionmaker(
    bind=_engine,
    expire_on_commit=False,   # keeps ORM objects usable after commit
    class_=AsyncSession,
)


# ── Declarative base ──────────────────────────────────────────────────────────
class Base(DeclarativeBase):
    """Base class for all ORM models.  Metadata is shared across the application."""
    pass


# ── Session helpers ────────────────────────────────────────────────────────────

@asynccontextmanager
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Async context manager that yields a database session and handles commit/rollback.

    Usage:
        async with get_db_session() as session:
            result = await session.execute(...)

    FastAPI dependency wrapper (Phase 4):
        async def db_dep() -> AsyncGenerator[AsyncSession, None]:
            async with get_db_session() as session:
                yield session
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def get_session_factory(database_url: str) -> async_sessionmaker:
    """
    Create a new session factory bound to the given URL.

    Used by tests to inject an isolated in-memory SQLite database without
    touching the module-level engine.
    """
    engine = create_async_engine(database_url, echo=False, pool_pre_ping=False)
    return async_sessionmaker(
        bind=engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )
