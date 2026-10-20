"""
tests/test_simulator.py

Tests for the SimulatorEngine and fault scenarios.

Covered:
- Determinism: same seed → same output
- Batch structure: correct asset/tag coverage, timestamp ordering, UTC-aware
- Normal operation: all values within critical limits
- Pump overheat: temperature exceeds nominal range within expected steps
- Motor vibration: vibration exceeds warning threshold
- Compressor pressure: discharge pressure exceeds warning threshold
- Sensor fault: some readings return BAD/NO_DATA quality
- Tag isolation: each asset only emits its own tags
- Physical plausibility: clamping prevents impossible values
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.models.measurement import DataQuality, DataSource, Measurement
from app.simulator.assets import ASSET_REGISTRY
from app.simulator.engine import SimulatorEngine
from app.simulator.ranges import OPERATING_RANGES
from app.simulator.scenarios import SCENARIOS, SCENARIO_NORMAL

FIXED_SEED = 42
FIXED_START = datetime(2024, 1, 15, 8, 0, 0, tzinfo=timezone.utc)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def get_readings(batch: list[Measurement], asset_id: str, tag_name: str) -> list[Measurement]:
    return [m for m in batch if m.asset_id == asset_id and m.tag_name == tag_name]


def make_engine(scenario_name: str, seed: int = FIXED_SEED) -> SimulatorEngine:
    return SimulatorEngine(
        scenario=SCENARIOS[scenario_name],
        seed=seed,
        start_time=FIXED_START,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Determinism
# ─────────────────────────────────────────────────────────────────────────────

class TestDeterminism:
    def test_same_seed_same_output(self):
        """Two engines with identical configuration must produce identical measurements."""
        e1 = make_engine("normal", seed=42)
        e2 = make_engine("normal", seed=42)
        batch1 = e1.generate_batch(n_steps=5)
        batch2 = e2.generate_batch(n_steps=5)
        assert len(batch1) == len(batch2)
        for m1, m2 in zip(batch1, batch2):
            assert m1.value == m2.value
            assert m1.quality == m2.quality
            assert m1.timestamp == m2.timestamp

    def test_different_seeds_differ(self):
        """Different seeds must produce at least one different value."""
        e1 = make_engine("normal", seed=1)
        e2 = make_engine("normal", seed=999)
        b1 = e1.generate_batch(n_steps=3)
        b2 = e2.generate_batch(n_steps=3)
        values1 = [m.value for m in b1 if m.value is not None]
        values2 = [m.value for m in b2 if m.value is not None]
        assert values1 != values2

    def test_sequential_calls_continue_timeline(self):
        """Calling generate_batch twice should advance the timeline, not repeat it."""
        e = make_engine("normal")
        batch1 = e.generate_batch(n_steps=2, interval_seconds=5)
        batch2 = e.generate_batch(n_steps=2, interval_seconds=5)
        # Last timestamp of batch1 should be before first of batch2
        assert batch1[-1].timestamp < batch2[0].timestamp


# ─────────────────────────────────────────────────────────────────────────────
# Batch structure
# ─────────────────────────────────────────────────────────────────────────────

class TestBatchStructure:
    def test_batch_covers_all_assets_and_tags(self, normal_engine):
        """
        One step must produce exactly one measurement per (asset, tag) pair.
        Total = sum of tag counts across all assets.
        """
        expected_count = sum(len(a.tags) for a in ASSET_REGISTRY.values())
        batch = normal_engine.generate_batch(n_steps=1)
        assert len(batch) == expected_count

    def test_n_steps_multiplies_count(self, normal_engine):
        tags_per_step = sum(len(a.tags) for a in ASSET_REGISTRY.values())
        batch = normal_engine.generate_batch(n_steps=4)
        assert len(batch) == 4 * tags_per_step

    def test_timestamps_are_utc_aware(self, normal_engine):
        batch = normal_engine.generate_batch(n_steps=2)
        for m in batch:
            assert m.timestamp.tzinfo is not None

    def test_timestamps_are_ordered(self, normal_engine):
        """Measurements within a batch must be non-decreasing by timestamp."""
        batch = normal_engine.generate_batch(n_steps=5, interval_seconds=10)
        timestamps = [m.timestamp for m in batch]
        assert timestamps == sorted(timestamps)

    def test_interval_respected(self, normal_engine):
        """Step n should be exactly n * interval_seconds after step 0."""
        interval = 10
        batch = normal_engine.generate_batch(n_steps=3, interval_seconds=interval)
        # Measurements for each asset in step 0 have timestamp = FIXED_START
        step0 = [m for m in batch if m.timestamp == FIXED_START]
        assert len(step0) > 0
        step2_ts = FIXED_START + timedelta(seconds=2 * interval)
        step2 = [m for m in batch if m.timestamp == step2_ts]
        assert len(step2) > 0

    def test_source_is_simulated(self, normal_engine):
        batch = normal_engine.generate_batch(n_steps=1)
        assert all(m.source == DataSource.SIMULATED for m in batch)

    def test_tag_isolation(self):
        """Each asset should only emit its own tags — no cross-asset contamination."""
        e = make_engine("normal")
        batch = e.generate_batch(n_steps=1)
        for asset_id, asset_def in ASSET_REGISTRY.items():
            allowed_tags = set(asset_def.tag_names())
            asset_readings = [m for m in batch if m.asset_id == asset_id]
            for m in asset_readings:
                assert m.tag_name in allowed_tags, (
                    f"{asset_id} emitted unexpected tag '{m.tag_name}'"
                )


# ─────────────────────────────────────────────────────────────────────────────
# Normal operation
# ─────────────────────────────────────────────────────────────────────────────

class TestNormalOperation:
    def test_values_within_critical_limits(self, normal_engine):
        """In normal operation no reading should breach critical thresholds."""
        batch = normal_engine.generate_batch(n_steps=20)
        for m in batch:
            if m.value is None:
                continue
            r = OPERATING_RANGES.get(m.asset_id, {}).get(m.tag_name)
            if r is None:
                continue
            assert m.value >= r.critical_low, (
                f"{m.asset_id}/{m.tag_name} = {m.value} below critical_low={r.critical_low}"
            )
            assert m.value <= r.critical_high, (
                f"{m.asset_id}/{m.tag_name} = {m.value} above critical_high={r.critical_high}"
            )

    def test_most_normal_readings_are_good_quality(self, normal_engine):
        batch = normal_engine.generate_batch(n_steps=10)
        good_count = sum(1 for m in batch if m.quality == DataQuality.GOOD)
        assert good_count / len(batch) > 0.7, "Expected >70% GOOD readings in normal operation"


# ─────────────────────────────────────────────────────────────────────────────
# Pump overheat scenario
# ─────────────────────────────────────────────────────────────────────────────

class TestPumpOverheat:
    def test_temperature_exceeds_nominal_range(self, pump_overheat_engine):
        """
        After enough steps the pump temperature should exceed its nominal_max.
        With drift_rate=1.2 and fixed_offset=10, this should happen within 15 steps.
        """
        batch = pump_overheat_engine.generate_batch(n_steps=15)
        temps = get_readings(batch, "PUMP-001", "temperature")
        r = OPERATING_RANGES["PUMP-001"]["temperature"]
        above_nominal = [m for m in temps if m.value is not None and m.value > r.nominal_max]
        assert len(above_nominal) > 0, (
            f"Expected pump temperature to exceed nominal_max={r.nominal_max} °C within 15 steps"
        )

    def test_other_assets_unaffected(self, pump_overheat_engine):
        """Motor and compressor should remain within warning limits in pump_overheat scenario."""
        batch = pump_overheat_engine.generate_batch(n_steps=10)
        for asset_id in ["MOTOR-001", "COMP-001"]:
            for m in batch:
                if m.asset_id != asset_id or m.value is None:
                    continue
                r = OPERATING_RANGES.get(asset_id, {}).get(m.tag_name)
                if r is None:
                    continue
                assert m.value <= r.warning_high, (
                    f"{asset_id}/{m.tag_name} breached warning_high in pump_overheat scenario"
                )


# ─────────────────────────────────────────────────────────────────────────────
# Motor vibration scenario
# ─────────────────────────────────────────────────────────────────────────────

class TestMotorVibration:
    def test_vibration_exceeds_warning_threshold(self, motor_vibration_engine):
        """
        Vibration should exceed the warning_high threshold within 10 steps
        due to the fixed_offset=5.0 mm/s perturbation.
        """
        batch = motor_vibration_engine.generate_batch(n_steps=10)
        vibs = get_readings(batch, "MOTOR-001", "vibration")
        r = OPERATING_RANGES["MOTOR-001"]["vibration"]
        above_warning = [m for m in vibs if m.value is not None and m.value > r.warning_high]
        assert len(above_warning) > 0, (
            f"Expected motor vibration > warning_high={r.warning_high} mm/s within 10 steps"
        )

    def test_pump_unaffected_by_motor_scenario(self, motor_vibration_engine):
        batch = motor_vibration_engine.generate_batch(n_steps=10)
        pump_temps = get_readings(batch, "PUMP-001", "temperature")
        r = OPERATING_RANGES["PUMP-001"]["temperature"]
        for m in pump_temps:
            if m.value is not None:
                assert m.value <= r.warning_high


# ─────────────────────────────────────────────────────────────────────────────
# Compressor pressure scenario
# ─────────────────────────────────────────────────────────────────────────────

class TestCompressorPressure:
    def test_discharge_pressure_exceeds_warning(self, comp_pressure_engine):
        """
        With fixed_offset=2.5 bar above the midpoint (~7.25 bar midpoint → reading ~9.75),
        the discharge pressure should exceed warning_high=9.5 bar from the first step.
        """
        batch = comp_pressure_engine.generate_batch(n_steps=5)
        readings = get_readings(batch, "COMP-001", "discharge_pressure")
        r = OPERATING_RANGES["COMP-001"]["discharge_pressure"]
        above_warning = [m for m in readings if m.value is not None and m.value > r.warning_high]
        assert len(above_warning) > 0, (
            f"Expected discharge_pressure > warning_high={r.warning_high} bar in comp_pressure scenario"
        )

    def test_power_draw_elevated(self, comp_pressure_engine):
        batch = comp_pressure_engine.generate_batch(n_steps=5)
        powers = get_readings(batch, "COMP-001", "power_draw")
        r = OPERATING_RANGES["COMP-001"]["power_draw"]
        above_nominal = [m for m in powers if m.value is not None and m.value > r.nominal_max]
        assert len(above_nominal) > 0, "Expected power_draw above nominal in comp_pressure scenario"


# ─────────────────────────────────────────────────────────────────────────────
# Sensor fault scenario
# ─────────────────────────────────────────────────────────────────────────────

class TestSensorFault:
    def test_some_readings_are_bad_or_no_data(self, sensor_fault_engine):
        """With 40% fault probability across all tags, at least some must be BAD/NO_DATA."""
        batch = sensor_fault_engine.generate_batch(n_steps=10)
        bad_count = sum(
            1 for m in batch if m.quality in (DataQuality.BAD, DataQuality.NO_DATA)
        )
        assert bad_count > 0, "Expected at least some BAD/NO_DATA readings in sensor_fault scenario"

    def test_bad_readings_have_no_value(self, sensor_fault_engine):
        batch = sensor_fault_engine.generate_batch(n_steps=10)
        for m in batch:
            if m.quality in (DataQuality.BAD, DataQuality.NO_DATA):
                assert m.value is None, (
                    f"BAD/NO_DATA reading should not carry a numeric value: {m}"
                )

    def test_some_readings_still_good(self, sensor_fault_engine):
        """With 40% fault probability, ~60% should be GOOD — verify some are."""
        batch = sensor_fault_engine.generate_batch(n_steps=10)
        good_count = sum(1 for m in batch if m.quality == DataQuality.GOOD)
        assert good_count > 0, "Expected some GOOD readings even in sensor_fault scenario"

    def test_reproducible_fault_pattern(self):
        """Same seed must produce the same pattern of BAD readings."""
        e1 = SimulatorEngine(scenario=SCENARIOS["sensor_fault"], seed=7, start_time=FIXED_START)
        e2 = SimulatorEngine(scenario=SCENARIOS["sensor_fault"], seed=7, start_time=FIXED_START)
        b1 = e1.generate_batch(n_steps=5)
        b2 = e2.generate_batch(n_steps=5)
        q1 = [m.quality for m in b1]
        q2 = [m.quality for m in b2]
        assert q1 == q2


# ─────────────────────────────────────────────────────────────────────────────
# Physical plausibility (clamping)
# ─────────────────────────────────────────────────────────────────────────────

class TestPhysicalPlausibility:
    def test_values_never_below_half_critical_low(self):
        """
        The engine clamps values to critical_low - 50% of critical range.
        No physically impossible readings should appear even after many steps.
        """
        for scenario_name in SCENARIOS:
            e = make_engine(scenario_name)
            batch = e.generate_batch(n_steps=30)
            for m in batch:
                if m.value is None:
                    continue
                r = OPERATING_RANGES.get(m.asset_id, {}).get(m.tag_name)
                if r is None:
                    continue
                half_critical = (r.critical_high - r.critical_low) * 0.5
                lower_bound = r.critical_low - half_critical
                assert m.value >= lower_bound, (
                    f"{scenario_name}/{m.asset_id}/{m.tag_name} = {m.value} "
                    f"below physical lower bound {lower_bound}"
                )

    def test_values_never_above_half_critical_high(self):
        for scenario_name in SCENARIOS:
            e = make_engine(scenario_name)
            batch = e.generate_batch(n_steps=30)
            for m in batch:
                if m.value is None:
                    continue
                r = OPERATING_RANGES.get(m.asset_id, {}).get(m.tag_name)
                if r is None:
                    continue
                half_critical = (r.critical_high - r.critical_low) * 0.5
                upper_bound = r.critical_high + half_critical
                assert m.value <= upper_bound, (
                    f"{scenario_name}/{m.asset_id}/{m.tag_name} = {m.value} "
                    f"above physical upper bound {upper_bound}"
                )
