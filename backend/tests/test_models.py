"""
tests/test_models.py

Unit tests for Pydantic data models (Measurement, enums, validators).

These tests exercise the data contract independently of the simulator so that
changes to either can be diagnosed separately.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest

from app.models.measurement import DataQuality, DataSource, Measurement


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def make_measurement(**overrides) -> Measurement:
    """Create a valid Measurement with sensible defaults, then apply overrides."""
    defaults = dict(
        asset_id="PUMP-001",
        asset_name="Cooling Water Pump",
        tag_name="temperature",
        unit="°C",
        value=42.0,
        quality=DataQuality.GOOD,
        source=DataSource.SIMULATED,
        timestamp=datetime(2024, 1, 15, 8, 0, 0, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return Measurement(**defaults)


# ─────────────────────────────────────────────────────────────────────────────
# Timestamp validation
# ─────────────────────────────────────────────────────────────────────────────

class TestTimestampValidation:
    def test_utc_aware_timestamp_accepted(self):
        m = make_measurement(timestamp=datetime(2024, 6, 1, 12, 0, tzinfo=timezone.utc))
        assert m.timestamp.tzinfo is not None

    def test_naive_timestamp_rejected(self):
        """A naive datetime must be rejected to prevent silent timezone bugs."""
        with pytest.raises(ValueError, match="timezone-aware"):
            make_measurement(timestamp=datetime(2024, 6, 1, 12, 0))  # no tzinfo

    def test_non_utc_timezone_normalised_to_utc(self):
        """Timestamps in other timezones should be stored as UTC."""
        ist = timezone(timedelta(hours=5, minutes=30))
        ts_ist = datetime(2024, 6, 1, 17, 30, tzinfo=ist)  # 12:00 UTC
        m = make_measurement(timestamp=ts_ist)
        assert m.timestamp.utcoffset().total_seconds() == 0
        assert m.timestamp.hour == 12


# ─────────────────────────────────────────────────────────────────────────────
# Quality / value consistency
# ─────────────────────────────────────────────────────────────────────────────

class TestQualityValueConsistency:
    def test_good_reading_with_value(self):
        m = make_measurement(quality=DataQuality.GOOD, value=55.0)
        assert m.quality == DataQuality.GOOD
        assert m.value == 55.0

    def test_bad_reading_without_value(self):
        m = make_measurement(quality=DataQuality.BAD, value=None)
        assert m.quality == DataQuality.BAD
        assert m.value is None

    def test_no_data_reading_without_value(self):
        m = make_measurement(quality=DataQuality.NO_DATA, value=None)
        assert m.quality == DataQuality.NO_DATA
        assert m.value is None

    def test_good_quality_with_none_value_demoted_to_uncertain(self):
        """
        A reading that claims GOOD quality but has no value is bumped to UNCERTAIN
        so downstream code knows the value is missing.
        """
        m = make_measurement(quality=DataQuality.GOOD, value=None)
        assert m.quality == DataQuality.UNCERTAIN

    def test_uncertain_with_none_value_stays_uncertain(self):
        m = make_measurement(quality=DataQuality.UNCERTAIN, value=None)
        assert m.quality == DataQuality.UNCERTAIN


# ─────────────────────────────────────────────────────────────────────────────
# is_valid_reading()
# ─────────────────────────────────────────────────────────────────────────────

class TestIsValidReading:
    def test_good_value_is_valid(self):
        assert make_measurement(quality=DataQuality.GOOD, value=42.0).is_valid_reading()

    def test_uncertain_value_is_valid(self):
        assert make_measurement(quality=DataQuality.UNCERTAIN, value=42.0).is_valid_reading()

    def test_bad_is_not_valid(self):
        assert not make_measurement(quality=DataQuality.BAD, value=None).is_valid_reading()

    def test_no_data_is_not_valid(self):
        assert not make_measurement(quality=DataQuality.NO_DATA, value=None).is_valid_reading()


# ─────────────────────────────────────────────────────────────────────────────
# DataSource enum
# ─────────────────────────────────────────────────────────────────────────────

class TestDataSource:
    def test_simulated_source(self):
        m = make_measurement(source=DataSource.SIMULATED)
        assert m.source == DataSource.SIMULATED

    def test_pi_system_source(self):
        m = make_measurement(source=DataSource.PI_SYSTEM)
        assert m.source == DataSource.PI_SYSTEM

    def test_pi_tag_path_optional(self):
        m = make_measurement(source=DataSource.PI_SYSTEM, pi_tag_path=r"\\SERVER\PUMP-001.Temperature")
        assert m.pi_tag_path is not None

    def test_pi_tag_path_none_by_default(self):
        m = make_measurement()
        assert m.pi_tag_path is None


# ─────────────────────────────────────────────────────────────────────────────
# Immutability
# ─────────────────────────────────────────────────────────────────────────────

class TestImmutability:
    def test_measurement_is_frozen(self):
        """Measurements are frozen Pydantic models; mutation must raise."""
        m = make_measurement()
        with pytest.raises(Exception):
            m.value = 99.0  # type: ignore[misc]
