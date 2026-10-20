"""
app/db/repositories/asset_repo.py

Async repository for asset and tag lookups.

Responsibilities
────────────────
• Retrieve the list of all known assets with their tags.
• Seed the asset catalogue from the ASSET_REGISTRY (idempotent — safe to call
  on every startup; uses INSERT OR IGNORE / ON CONFLICT DO NOTHING).

The repository receives an `AsyncSession` injected from outside so it is
fully testable with an isolated in-memory SQLite session.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import AssetORM, TagORM
from app.simulator.assets import ASSET_REGISTRY


class AssetRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── Queries ───────────────────────────────────────────────────────────────

    async def get_all(self) -> list[AssetORM]:
        """Return all assets with their tags eagerly loaded."""
        result = await self._session.execute(
            select(AssetORM).options(selectinload(AssetORM.tags)).order_by(AssetORM.asset_id)
        )
        return list(result.scalars().all())

    async def get_by_id(self, asset_id: str) -> AssetORM | None:
        """Return a single asset by its natural key, or None if not found."""
        result = await self._session.execute(
            select(AssetORM)
            .where(AssetORM.asset_id == asset_id)
            .options(selectinload(AssetORM.tags))
        )
        return result.scalar_one_or_none()

    async def exists(self, asset_id: str) -> bool:
        result = await self._session.execute(
            select(AssetORM.id).where(AssetORM.asset_id == asset_id)
        )
        return result.scalar_one_or_none() is not None

    # ── Seeding ────────────────────────────────────────────────────────────────

    async def seed_from_registry(self) -> int:
        """
        Insert assets and tags from ASSET_REGISTRY if they do not already exist.

        Returns the number of assets inserted (0 if all were already present).
        This is idempotent: safe to call on every application startup.
        """
        inserted = 0
        for asset_id, asset_def in ASSET_REGISTRY.items():
            # Check whether the asset already exists
            existing = await self.get_by_id(asset_id)
            if existing is not None:
                continue

            asset_orm = AssetORM(
                asset_id=asset_def.asset_id,
                asset_name=asset_def.asset_name,
                asset_type=asset_def.asset_type,
            )
            self._session.add(asset_orm)
            # Flush to get the PK before adding child tags
            await self._session.flush()

            for tag_def in asset_def.tags:
                self._session.add(
                    TagORM(
                        asset_id=asset_def.asset_id,
                        tag_name=tag_def.name,
                        unit=tag_def.unit,
                        description=tag_def.description,
                    )
                )
            inserted += 1

        return inserted
