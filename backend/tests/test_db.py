"""
tests/test_db.py

Repository integration tests using SQLite in-memory (via aiosqlite).

These tests prove that:
  1. Assets and tags can be seeded from the registry.
  2. Measurements can be inserted individually and in batches.
  3. get_latest_per_tag() returns the most recent reading per (asset, tag).
  4. get_history() filters correctly by time range and respects ordering.
  5. get_asset_history() returns all tags for one asset.
  6. get_recent_n() returns the N most recent readings in chronological order.
  7. count_in_range() returns accurate counts.
  8. Invalid time ranges raise ValueError.
  9. BAD-quality readings with None value round-trip correctly.

No PostgreSQL required — the session factory is overridden with an SQLite URL.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import AssetORM, MeasurementORM
from app.db.repositories.asset_repo import AssetRepository
from app.db.repositories.measurement_repo import MeasurementRepository, _validate_time_range
from app.models.measurement import DataQuality, DataSource, Measurement
from app.simulator.assets import ASSET_REGISTRY
from app.simulator.engine import SimulatorEngine
from app.simulator.scenarios import SCENARIOS

# ── Fixtures ──────────────────────────────────────────────────────────────────

SQLITE_URL = "sqlite+aiosqlite:///:memory:"
T0 = datetime(2024, 1, 15, 8, 0, 0, tzinfo=timezone.utc)


@pytest_asyncio.fixture
async def db_session():
    """
    Create an isolated in-memory SQLite database for each test.

    SQLite is not Postgres, but it supports all the query patterns we use.
    The schema is created via SQLAlchemy metadata (not Alembic) so tests
    run without a migration runner.
    """
    engine = create_async_engine(SQLITE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)

    async with session_factory() as session:
        yield session
        await session.rollback()  # discard all test writes

    await engine.dispose()


# ── Helper ────────────────────────────────────────────────────────────────────

def make_measurement(
    asset_id: str = "PUMP-001",
    tag_name: str = "temperature",
    value: float | None = 42.0,
    quality: DataQuality = DataQuality.GOOD,
    timestamp: datetime = T0,
    source: DataSource = DataSource.SIMULATED,
) -> Measurement:
    asset_names = {a.asset_id: a.asset_name for a in ASSET_REGISTRY.values()}
    return Measurement(
        asset_id=asset_id,
        asset_name=asset_names.get(asset_id, "Unknown"),
        tag_name=tag_name,
        unit="°C",
        value=value,
        quality=quality,
        source=source,
        timestamp=timestamp,
    )


# ── Asset repository tests ─────────────────────────────────────────────────────

class TestAssetRepository:
    async def test_seed_inserts_all_assets(self, db_session):
        repo = AssetRepository(db_session)
        inserted = await repo.seed_from_registry()
        assert inserted == len(ASSET_REGISTRY)

    async def test_seed_is_idempotent(self, db_session):
        repo = AssetRepository(db_session)
        await repo.seed_from_registry()
        second_run = await repo.seed_from_registry()
        assert second_run == 0  # nothing new inserted

    async def test_get_all_returns_expected_assets(self, db_session):
        repo = AssetRepository(db_session)
        await repo.seed_from_registry()
        await db_session.commit()
        assets = await repo.get_all()
        asset_ids = {a.asset_id for a in assets}
        assert asset_ids == set(ASSET_REGISTRY.keys())

    async def test_get_by_id_returns_correct_asset(self, db_session):
        repo = AssetRepository(db_session)
        await repo.seed_from_registry()
        await db_session.commit()
        asset = await repo.get_by_id("PUMP-001")
        assert asset is not None
        assert asset.asset_id == "PUMP-001"
        assert asset.asset_name == "Cooling Water Pump"

    async def test_get_by_id_missing_returns_none(self, db_session):
        repo = AssetRepository(db_session)
        await repo.seed_from_registry()
        await db_session.commit()
        result = await repo.get_by_id("DOES-NOT-EXIST")
        assert result is None

    async def test_tags_seeded_correctly(self, db_session):
        repo = AssetRepository(db_session)
        await repo.seed_from_registry()
        await db_session.commit()
        asset = await repo.get_by_id("MOTOR-001")
        assert asset is not None
        tag_names = {t.tag_name for t in asset.tags}
        expected = {"temperature", "vibration", "current", "rpm"}
        assert tag_names == expected

    async def test_exists_true_for_known_asset(self, db_session):
        repo = AssetRepository(db_session)
        await repo.seed_from_registry()
        await db_session.commit()
        assert await repo.exists("COMP-001") is True

    async def test_exists_false_for_unknown_asset(self, db_session):
        repo = AssetRepository(db_session)
        assert await repo.exists("GHOST-999") is False


# ── Measurement repository tests ──────────────────────────────────────────────

class TestMeasurementInsert:
    async def test_insert_single(self, db_session):
        # Seed asset first (FK constraint)
        await AssetRepository(db_session).seed_from_registry()
        await db_session.commit()

        repo = MeasurementRepository(db_session)
        orm = await repo.insert(make_measurement())
        await db_session.commit()
        assert orm.id is not None

    async def test_insert_bad_quality_none_value(self, db_session):
        await AssetRepository(db_session).seed_from_registry()
        await db_session.commit()

        m = make_measurement(value=None, quality=DataQuality.BAD)
        repo = MeasurementRepository(db_session)
        orm = await repo.insert(m)
        await db_session.commit()
        assert orm.value is None
        assert orm.quality == "BAD"

    async def test_insert_batch(self, db_session):
        await AssetRepository(db_session).seed_from_registry()
        await db_session.commit()

        engine = SimulatorEngine(scenario=SCENARIOS["normal"], seed=42, start_time=T0)
        batch = engine.generate_batch(n_steps=3)

        repo = MeasurementRepository(db_session)
        count = await repo.insert_batch(batch)
        await db_session.commit()
        assert count == len(batch)

    async def test_insert_pi_source_preserves_tag_path(self, db_session):
        await AssetRepository(db_session).seed_from_registry()
        await db_session.commit()

        m = Measurement(
            asset_id="PUMP-001",
            asset_name="Cooling Water Pump",
            tag_name="temperature",
            unit="°C",
            value=55.0,
            quality=DataQuality.GOOD,
            source=DataSource.PI_SYSTEM,
            timestamp=T0,
            pi_tag_path=r"\\SERVER\PUMP-001.Temperature",
        )
        repo = MeasurementRepository(db_session)
        orm = await repo.insert(m)
        await db_session.commit()
        assert orm.pi_tag_path == r"\\SERVER\PUMP-001.Temperature"
        assert orm.source == "PI_SYSTEM"


class TestLatestQueries:
    async def _seed_and_insert(self, db_session, n_steps=5) -> MeasurementRepository:
        await AssetRepository(db_session).seed_from_registry()
        await db_session.commit()
        engine = SimulatorEngine(scenario=SCENARIOS["normal"], seed=42, start_time=T0)
        batch = engine.generate_batch(n_steps=n_steps, interval_seconds=5)
        repo = MeasurementRepository(db_session)
        await repo.insert_batch(batch)
        await db_session.commit()
        return repo

    async def test_get_latest_per_tag_all_assets(self, db_session):
        repo = await self._seed_and_insert(db_session)
        latest = await repo.get_latest_per_tag()
        # Should have one row per (asset, tag) pair
        expected_count = sum(len(a.tags) for a in ASSET_REGISTRY.values())
        assert len(latest) == expected_count

    async def test_get_latest_per_tag_filtered_by_asset(self, db_session):
        repo = await self._seed_and_insert(db_session)
        latest = await repo.get_latest_per_tag(asset_id="PUMP-001")
        assert all(m.asset_id == "PUMP-001" for m in latest)
        from app.simulator.assets import PUMP_001
        assert len(latest) == len(PUMP_001.tags)

    async def test_latest_is_actually_most_recent(self, db_session):
        """The returned timestamp should be the maximum for that (asset, tag).

        SQLite strips timezone info from DateTime columns; we normalise to UTC
        before comparing so the test passes on both SQLite (tests) and Postgres (prod).
        """
        repo = await self._seed_and_insert(db_session, n_steps=5)
        latest = await repo.get_latest_per_tag(asset_id="PUMP-001")
        # Normalise to UTC (SQLite returns naive datetimes, Postgres returns aware)
        max_ts = max(
            m.timestamp.replace(tzinfo=timezone.utc) if m.timestamp.tzinfo is None
            else m.timestamp
            for m in latest
        )
        # With 5 steps at 5s each, the last ts is T0 + 20s
        expected_last = T0 + timedelta(seconds=4 * 5)
        assert max_ts == expected_last

    async def test_get_latest_for_tag(self, db_session):
        repo = await self._seed_and_insert(db_session)
        row = await repo.get_latest_for_tag("MOTOR-001", "vibration")
        assert row is not None
        assert row.asset_id == "MOTOR-001"
        assert row.tag_name == "vibration"

    async def test_get_latest_for_tag_missing_returns_none(self, db_session):
        repo = await self._seed_and_insert(db_session)
        row = await repo.get_latest_for_tag("PUMP-001", "nonexistent_tag")
        assert row is None


class TestHistoricalQueries:
    async def _seed(self, db_session, n_steps=10) -> MeasurementRepository:
        await AssetRepository(db_session).seed_from_registry()
        await db_session.commit()
        engine = SimulatorEngine(scenario=SCENARIOS["normal"], seed=42, start_time=T0)
        batch = engine.generate_batch(n_steps=n_steps, interval_seconds=60)
        repo = MeasurementRepository(db_session)
        await repo.insert_batch(batch)
        await db_session.commit()
        return repo

    async def test_get_history_returns_ordered_asc(self, db_session):
        repo = await self._seed(db_session)
        rows = await repo.get_history(
            "PUMP-001", "temperature",
            start=T0,
            end=T0 + timedelta(hours=1),
        )
        assert rows == sorted(rows, key=lambda r: r.timestamp)

    async def test_get_history_respects_time_range(self, db_session):
        """Readings outside the time range must not appear.

        SQLite strips timezone info — normalise before comparing.
        """
        repo = await self._seed(db_session)
        # Only ask for steps 2-4 (T0+2min to T0+4min inclusive)
        start = T0 + timedelta(minutes=2)
        end = T0 + timedelta(minutes=4)
        rows = await repo.get_history("PUMP-001", "temperature", start=start, end=end)
        for r in rows:
            ts = r.timestamp.replace(tzinfo=timezone.utc) if r.timestamp.tzinfo is None else r.timestamp
            assert start <= ts <= end

    async def test_get_history_empty_range_returns_empty(self, db_session):
        repo = await self._seed(db_session)
        # Ask for a time range well before any data was inserted
        rows = await repo.get_history(
            "PUMP-001", "temperature",
            start=T0 - timedelta(days=7),
            end=T0 - timedelta(days=6),
        )
        assert rows == []

    async def test_get_history_invalid_range_raises(self, db_session):
        repo = await self._seed(db_session)
        with pytest.raises(ValueError, match="must be after start"):
            await repo.get_history(
                "PUMP-001", "temperature",
                start=T0 + timedelta(hours=1),
                end=T0,                          # end before start
            )

    async def test_get_history_naive_timestamps_raise(self, db_session):
        repo = await self._seed(db_session)
        naive = datetime(2024, 1, 15, 8, 0, 0)  # no tzinfo
        with pytest.raises(ValueError):
            await repo.get_history("PUMP-001", "temperature", start=naive, end=T0)

    async def test_get_asset_history_covers_all_tags(self, db_session):
        repo = await self._seed(db_session)
        rows = await repo.get_asset_history(
            "MOTOR-001",
            start=T0,
            end=T0 + timedelta(hours=1),
        )
        tag_names = {r.tag_name for r in rows}
        from app.simulator.assets import MOTOR_001
        assert tag_names == set(MOTOR_001.tag_names())

    async def test_get_recent_n_chronological(self, db_session):
        repo = await self._seed(db_session, n_steps=10)
        rows = await repo.get_recent_n("COMP-001", "discharge_pressure", n=5)
        assert len(rows) == 5
        assert rows == sorted(rows, key=lambda r: r.timestamp)

    async def test_count_in_range(self, db_session):
        repo = await self._seed(db_session, n_steps=10)
        # 10 steps → 10 readings for (PUMP-001, temperature)
        count = await repo.count_in_range(
            "PUMP-001", "temperature",
            start=T0,
            end=T0 + timedelta(hours=1),
        )
        assert count == 10


class TestTimeRangeValidation:
    """Unit tests for _validate_time_range helper (no DB needed)."""

    def test_valid_range_passes(self):
        _validate_time_range(T0, T0 + timedelta(hours=1))  # must not raise

    def test_reversed_range_raises(self):
        with pytest.raises(ValueError, match="must be after start"):
            _validate_time_range(T0 + timedelta(hours=1), T0)

    def test_equal_timestamps_raise(self):
        with pytest.raises(ValueError, match="must be after start"):
            _validate_time_range(T0, T0)

    def test_naive_start_raises(self):
        with pytest.raises(ValueError, match="UTC-aware"):
            _validate_time_range(datetime(2024, 1, 1), T0)

    def test_naive_end_raises(self):
        with pytest.raises(ValueError, match="UTC-aware"):
            _validate_time_range(T0, datetime(2024, 1, 1))
