"""
tests/conftest.py

Shared pytest fixtures for the Northstar test suite.

Phase 1 fixtures focus on the simulator and models only.
Later phases will add database and API client fixtures here.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.simulator.assets import ASSET_REGISTRY
from app.simulator.engine import SimulatorEngine
from app.simulator.scenarios import SCENARIOS, SCENARIO_NORMAL


FIXED_SEED = 42
FIXED_START = datetime(2024, 1, 15, 8, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def normal_engine() -> SimulatorEngine:
    """Engine running normal operation scenario with a fixed seed and start time."""
    return SimulatorEngine(
        scenario=SCENARIO_NORMAL,
        seed=FIXED_SEED,
        start_time=FIXED_START,
    )


@pytest.fixture
def pump_overheat_engine() -> SimulatorEngine:
    return SimulatorEngine(
        scenario=SCENARIOS["pump_overheat"],
        seed=FIXED_SEED,
        start_time=FIXED_START,
    )


@pytest.fixture
def motor_vibration_engine() -> SimulatorEngine:
    return SimulatorEngine(
        scenario=SCENARIOS["motor_vibration"],
        seed=FIXED_SEED,
        start_time=FIXED_START,
    )


@pytest.fixture
def comp_pressure_engine() -> SimulatorEngine:
    return SimulatorEngine(
        scenario=SCENARIOS["comp_pressure"],
        seed=FIXED_SEED,
        start_time=FIXED_START,
    )


@pytest.fixture
def sensor_fault_engine() -> SimulatorEngine:
    return SimulatorEngine(
        scenario=SCENARIOS["sensor_fault"],
        seed=FIXED_SEED,
        start_time=FIXED_START,
    )
