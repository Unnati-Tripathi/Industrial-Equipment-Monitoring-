"""
app/db/repositories/measurement_repo.py

Async repository for measurement persistence and historical queries.

Query patterns supported
────────────────────────
1. Insert one or a batch of measurements (e.g. from the simulator poller).
2. Retrieve the latest known reading for every (asset, tag) pair — used by the
   dashboard "current values" panel.
3. Historical time-range query for one (asset, tag) pair — used by trend charts.
4. Historical time-range query for all tags on one asset — used by asset detail page.
5. Retrieve the most recent N readings for a tag (useful for alert engine lookups).

Performance notes
─────────────────
• All queries use the composite index `ix_measurements_asset_tag_time`.
• `get_latest_per_tag()` uses a subquery to find the MAX(timestamp) per
  (asset_id, tag_name) group, then fetches the matching rows.  This is more
  portable than a DISTINCT ON (Postgres-only) while still being efficient with
  the index.
• Caller controls pagination via `limit` and `offset` arguments.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence

from sqlalchemy import func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import MeasurementORM
from app.models.measurement import Measurement


class MeasurementRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── Write ─────────────────────────────────────────────────────────────────

    async def insert(self, measurement: Measurement) -> MeasurementORM:
        """Persist a single Measurement Pydantic object and return the ORM row."""
        orm = _to_orm(measurement)
        self._session.add(orm)
        await self._session.flush()   # populates orm.id without committing
        return orm

    async def insert_batch(self, measurements: list[Measurement]) -> int:
        """
        Bulk-insert a list of measurements.

        Uses add_all + flush rather than bulk_insert_mappings so that
        SQLAlchemy relationship event hooks still fire (useful for Phase 3).
        Returns the number of rows inserted.
        """
        if not measurements:
            return 0
        orm_rows = [_to_orm(m) for m in measurements]
        self._session.add_all(orm_rows)
        await self._session.flush()
        return len(orm_rows)

    # ── Latest values ─────────────────────────────────────────────────────────

    async def get_latest_per_tag(
        self,
        asset_id: str | None = None,
    ) -> list[MeasurementORM]:
        """
        Return the most recent measurement for each (asset_id, tag_name) pair.

        If `asset_id` is provided, results are limited to that asset.
        This is the primary query used by the dashboard's "current values" panel.
        """
        # Subquery: find MAX(timestamp) for each (asset_id, tag_name)
        sub = select(
            MeasurementORM.asset_id,
            MeasurementORM.tag_name,
            func.max(MeasurementORM.timestamp).label("max_ts"),
        ).group_by(MeasurementORM.asset_id, MeasurementORM.tag_name)

        if asset_id:
            sub = sub.where(MeasurementORM.asset_id == asset_id)

        sub = sub.subquery()

        # Main query: join back to get the full row for each max timestamp
        stmt = select(MeasurementORM).join(
            sub,
            (MeasurementORM.asset_id == sub.c.asset_id)
            & (MeasurementORM.tag_name == sub.c.tag_name)
            & (MeasurementORM.timestamp == sub.c.max_ts),
        ).order_by(MeasurementORM.asset_id, MeasurementORM.tag_name)

        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_latest_for_tag(
        self, asset_id: str, tag_name: str
    ) -> MeasurementORM | None:
        """Return the single most recent reading for one (asset, tag) pair."""
        result = await self._session.execute(
            select(MeasurementORM)
            .where(
                MeasurementORM.asset_id == asset_id,
                MeasurementORM.tag_name == tag_name,
            )
            .order_by(MeasurementORM.timestamp.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    # ── Historical queries ────────────────────────────────────────────────────

    async def get_history(
        self,
        asset_id: str,
        tag_name: str,
        start: datetime,
        end: datetime,
        limit: int = 1000,
        offset: int = 0,
    ) -> list[MeasurementORM]:
        """
        Return measurements for one tag in a time range, ordered oldest-first.

        Parameters
        ----------
        start, end : datetime
            Must be UTC-aware.  Raises ValueError if end <= start.
        limit : int
            Maximum rows to return (capped at 5000 to protect memory).
        offset : int
            Pagination offset.
        """
        _validate_time_range(start, end)
        limit = min(limit, 5000)

        result = await self._session.execute(
            select(MeasurementORM)
            .where(
                MeasurementORM.asset_id == asset_id,
                MeasurementORM.tag_name == tag_name,
                MeasurementORM.timestamp >= start,
                MeasurementORM.timestamp <= end,
            )
            .order_by(MeasurementORM.timestamp.asc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def get_asset_history(
        self,
        asset_id: str,
        start: datetime,
        end: datetime,
        limit: int = 5000,
        offset: int = 0,
    ) -> list[MeasurementORM]:
        """
        Return all tag measurements for one asset in a time range.

        Ordered by (timestamp ASC, tag_name ASC) so readings for the same
        timestamp are grouped together — convenient for building a snapshot table.
        """
        _validate_time_range(start, end)
        limit = min(limit, 10_000)

        result = await self._session.execute(
            select(MeasurementORM)
            .where(
                MeasurementORM.asset_id == asset_id,
                MeasurementORM.timestamp >= start,
                MeasurementORM.timestamp <= end,
            )
            .order_by(MeasurementORM.timestamp.asc(), MeasurementORM.tag_name.asc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def get_recent_n(
        self,
        asset_id: str,
        tag_name: str,
        n: int = 10,
    ) -> list[MeasurementORM]:
        """
        Return the N most recent readings for one tag, newest-first.

        Used by the alert engine to inspect the last few readings when
        evaluating whether a fault is continuing or has recovered.
        """
        result = await self._session.execute(
            select(MeasurementORM)
            .where(
                MeasurementORM.asset_id == asset_id,
                MeasurementORM.tag_name == tag_name,
            )
            .order_by(MeasurementORM.timestamp.desc())
            .limit(n)
        )
        # Return in chronological order for the caller's convenience
        rows = list(result.scalars().all())
        return list(reversed(rows))

    async def count_in_range(
        self,
        asset_id: str,
        tag_name: str,
        start: datetime,
        end: datetime,
    ) -> int:
        """Return the row count for a given time range — used for pagination metadata."""
        _validate_time_range(start, end)
        result = await self._session.execute(
            select(func.count()).where(
                MeasurementORM.asset_id == asset_id,
                MeasurementORM.tag_name == tag_name,
                MeasurementORM.timestamp >= start,
                MeasurementORM.timestamp <= end,
            )
        )
        return result.scalar_one()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _to_orm(m: Measurement) -> MeasurementORM:
    """Convert a Pydantic Measurement to an ORM row without committing."""
    return MeasurementORM(
        asset_id=m.asset_id,
        asset_name=m.asset_name,
        tag_name=m.tag_name,
        unit=m.unit,
        value=m.value,
        quality=m.quality.value,
        source=m.source.value,
        timestamp=m.timestamp,
        pi_tag_path=m.pi_tag_path,
    )


def _validate_time_range(start: datetime, end: datetime) -> None:
    """Raise ValueError for invalid or backwards time ranges."""
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("start and end must be UTC-aware datetimes")
    if end <= start:
        raise ValueError(
            f"end ({end.isoformat()}) must be after start ({start.isoformat()})"
        )
    # Sanity check: reject ranges further than 5 years in the future
    five_years_out = datetime.now(timezone.utc).replace(year=datetime.now().year + 5)
    if start > five_years_out or end > five_years_out:
        raise ValueError("Time range is implausibly far in the future")
