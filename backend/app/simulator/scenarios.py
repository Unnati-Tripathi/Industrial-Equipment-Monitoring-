"""
app/simulator/scenarios.py

Fault scenario definitions.

A ScenarioConfig describes how the simulator should deviate from normal operation.
Each scenario targets specific (asset_id, tag_name) pairs and specifies:

    drift_rate      – additional value added per time-step (can be negative).
                      Allows gradual ramp-up of a fault over multiple steps.
    noise_scale     – multiplier applied to the standard noise amplitude for this tag.
                      >1.0 = noisier; useful for vibration faults.
    fixed_offset    – constant offset added on top of the nominal midpoint.
                      Simulates a calibration drift or sensor offset.
    quality_override – force a specific DataQuality code (e.g. BAD, NO_DATA).
                       When set, value is set to None.
    fault_probability – for sensor_fault scenario: probability 0–1 that a given
                        reading returns bad quality instead of a value.

A tag not mentioned in perturbations behaves normally (baseline noise only).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from app.models.measurement import DataQuality


@dataclass
class TagPerturbation:
    """Describes how one tag deviates from its nominal range during a scenario."""

    drift_rate: float = 0.0          # per time-step added to the running value
    noise_scale: float = 1.0         # multiplier on baseline noise
    fixed_offset: float = 0.0        # constant offset from nominal midpoint
    quality_override: Optional[DataQuality] = None
    fault_probability: float = 0.0   # 0 = never, 1 = always produce bad quality


@dataclass
class ScenarioConfig:
    """
    Complete configuration for one named scenario.

    perturbations: maps (asset_id, tag_name) → TagPerturbation.
    description: human-readable summary shown on the dashboard.
    """

    name: str
    description: str
    # key format: "ASSET-ID:tag_name"
    perturbations: dict[str, TagPerturbation] = field(default_factory=dict)

    def get_perturbation(self, asset_id: str, tag_name: str) -> TagPerturbation:
        key = f"{asset_id}:{tag_name}"
        return self.perturbations.get(key, TagPerturbation())


# ─────────────────────────────────────────────────────────────────────────────
# 1. Normal operation
# ─────────────────────────────────────────────────────────────────────────────
SCENARIO_NORMAL = ScenarioConfig(
    name="normal",
    description="All equipment operating within normal parameters. Baseline Gaussian noise only.",
    perturbations={},
)

# ─────────────────────────────────────────────────────────────────────────────
# 2. Pump overheating
# Scenario: bearing friction increases due to lubrication failure.
# Temperature rises gradually; flow rate drops as cavitation begins.
# Other pump sensors remain within warning limits at the start.
# ─────────────────────────────────────────────────────────────────────────────
SCENARIO_PUMP_OVERHEAT = ScenarioConfig(
    name="pump_overheat",
    description=(
        "PUMP-001 bearing temperature rising steadily — possible lubrication failure. "
        "Flow rate dropping as cavitation develops."
    ),
    perturbations={
        "PUMP-001:temperature": TagPerturbation(
            drift_rate=1.2,      # rises ~1.2 °C per step
            noise_scale=1.5,
            fixed_offset=10.0,   # starts 10 °C above nominal midpoint
        ),
        "PUMP-001:flow_rate": TagPerturbation(
            drift_rate=-0.15,    # slow decline
            noise_scale=2.0,     # noisier as cavitation develops
        ),
        "PUMP-001:outlet_pressure": TagPerturbation(
            drift_rate=-0.05,    # slightly reduced head as flow drops
        ),
    },
)

# ─────────────────────────────────────────────────────────────────────────────
# 3. Excessive motor vibration
# Scenario: rotor imbalance or bearing defect.
# Vibration spikes; RPM may fluctuate; current rises slightly.
# ─────────────────────────────────────────────────────────────────────────────
SCENARIO_MOTOR_VIBRATION = ScenarioConfig(
    name="motor_vibration",
    description=(
        "MOTOR-001 showing elevated radial vibration — possible rotor imbalance or "
        "bearing defect. RPM fluctuating and current slightly elevated."
    ),
    perturbations={
        "MOTOR-001:vibration": TagPerturbation(
            fixed_offset=5.0,    # starts well above warning threshold
            noise_scale=3.5,     # high noise simulates impact-type vibration
            drift_rate=0.3,      # slowly worsening
        ),
        "MOTOR-001:rpm": TagPerturbation(
            noise_scale=4.0,     # speed hunting under load imbalance
        ),
        "MOTOR-001:current": TagPerturbation(
            fixed_offset=8.0,    # slightly elevated due to increased load
            noise_scale=1.8,
        ),
    },
)

# ─────────────────────────────────────────────────────────────────────────────
# 4. Compressor high discharge pressure
# Scenario: downstream valve partially closed or downstream piping blockage.
# Pressure climbs; power draw rises; inlet pressure slightly low.
# ─────────────────────────────────────────────────────────────────────────────
SCENARIO_COMP_PRESSURE = ScenarioConfig(
    name="comp_pressure",
    description=(
        "COMP-001 discharge pressure abnormally high — possible downstream blockage. "
        "Power draw elevated as compressor works against back-pressure."
    ),
    perturbations={
        "COMP-001:discharge_pressure": TagPerturbation(
            fixed_offset=2.5,    # starts ~2.5 bar above nominal midpoint
            drift_rate=0.08,     # continues rising
            noise_scale=1.2,
        ),
        "COMP-001:power_draw": TagPerturbation(
            fixed_offset=6.0,    # power rises with pressure
            drift_rate=0.05,
            noise_scale=1.3,
        ),
        "COMP-001:temperature": TagPerturbation(
            fixed_offset=8.0,    # discharge temp rises with pressure ratio
            drift_rate=0.1,
            noise_scale=1.1,
        ),
    },
)

# ─────────────────────────────────────────────────────────────────────────────
# 5. Sensor fault (missing / invalid readings)
# Scenario: communication faults or instrument failures across all assets.
# A random subset of readings report BAD or NO_DATA on each step.
# ─────────────────────────────────────────────────────────────────────────────
# We set a fault_probability per tag; the engine samples this per reading.
_FAULT_PROB = 0.4   # 40% chance each tag returns bad quality per step

def _all_assets_fault_perturbations() -> dict[str, TagPerturbation]:
    """Build perturbation dict for every tag on every asset in the plant."""
    from app.simulator.assets import ASSET_REGISTRY

    result: dict[str, TagPerturbation] = {}
    for asset_id, asset_def in ASSET_REGISTRY.items():
        for tag in asset_def.tags:
            result[f"{asset_id}:{tag.name}"] = TagPerturbation(
                fault_probability=_FAULT_PROB,
            )
    return result


SCENARIO_SENSOR_FAULT = ScenarioConfig(
    name="sensor_fault",
    description=(
        "Communication faults and instrument errors across multiple sensors. "
        "Expect BAD and NO_DATA readings. Data shown on the dashboard may be incomplete."
    ),
    perturbations=_all_assets_fault_perturbations(),
)

# ─────────────────────────────────────────────────────────────────────────────
# Public registry — looked up by name string from config / CLI
# ─────────────────────────────────────────────────────────────────────────────
SCENARIOS: dict[str, ScenarioConfig] = {
    s.name: s
    for s in [
        SCENARIO_NORMAL,
        SCENARIO_PUMP_OVERHEAT,
        SCENARIO_MOTOR_VIBRATION,
        SCENARIO_COMP_PRESSURE,
        SCENARIO_SENSOR_FAULT,
    ]
}
