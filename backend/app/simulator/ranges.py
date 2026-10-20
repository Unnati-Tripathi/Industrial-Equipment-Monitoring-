"""
app/simulator/ranges.py

Normal operating ranges and alert thresholds for every sensor tag on every asset.

Structure per tag:
    nominal_min / nominal_max   – healthy baseline; random noise stays within these.
    warning_low / warning_high  – first alarm level (operator attention required).
    critical_low / critical_high– second alarm level (immediate action required).
    unit                        – must match the TagDefinition unit.

Values are drawn from typical published specifications for similar equipment
(small centrifugal pump, 75 kW induction motor, 7-bar reciprocating compressor).
They are illustrative, not certified engineering data.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TagRange:
    nominal_min: float
    nominal_max: float
    warning_low: float
    warning_high: float
    critical_low: float
    critical_high: float
    unit: str


# Maps asset_id → tag_name → TagRange
OPERATING_RANGES: dict[str, dict[str, TagRange]] = {
    "PUMP-001": {
        "temperature": TagRange(
            nominal_min=25.0, nominal_max=55.0,
            warning_low=20.0, warning_high=65.0,
            critical_low=15.0, critical_high=80.0,
            unit="°C",
        ),
        "flow_rate": TagRange(
            nominal_min=18.0, nominal_max=22.0,
            warning_low=14.0, warning_high=25.0,
            critical_low=10.0, critical_high=28.0,
            unit="m³/h",
        ),
        "inlet_pressure": TagRange(
            nominal_min=0.8, nominal_max=1.5,
            warning_low=0.5, warning_high=1.8,
            critical_low=0.3, critical_high=2.2,
            unit="bar",
        ),
        "outlet_pressure": TagRange(
            nominal_min=3.5, nominal_max=4.5,
            warning_low=3.0, warning_high=5.0,
            critical_low=2.5, critical_high=6.0,
            unit="bar",
        ),
    },
    "MOTOR-001": {
        "temperature": TagRange(
            nominal_min=40.0, nominal_max=70.0,
            warning_low=35.0, warning_high=80.0,
            critical_low=20.0, critical_high=95.0,
            unit="°C",
        ),
        "vibration": TagRange(
            nominal_min=0.5, nominal_max=4.5,
            warning_low=0.2, warning_high=7.1,   # ISO 10816 zone B→C boundary
            critical_low=0.1, critical_high=11.2, # ISO 10816 zone C→D boundary
            unit="mm/s",
        ),
        "current": TagRange(
            nominal_min=55.0, nominal_max=75.0,
            warning_low=45.0, warning_high=85.0,
            critical_low=30.0, critical_high=100.0,
            unit="A",
        ),
        "rpm": TagRange(
            nominal_min=1450.0, nominal_max=1500.0,
            warning_low=1400.0, warning_high=1520.0,
            critical_low=1350.0, critical_high=1550.0,
            unit="RPM",
        ),
    },
    "COMP-001": {
        "temperature": TagRange(
            nominal_min=60.0, nominal_max=90.0,
            warning_low=50.0, warning_high=100.0,
            critical_low=40.0, critical_high=115.0,
            unit="°C",
        ),
        "discharge_pressure": TagRange(
            nominal_min=6.5, nominal_max=8.0,
            warning_low=5.5, warning_high=9.5,
            critical_low=4.0, critical_high=11.0,
            unit="bar",
        ),
        "inlet_pressure": TagRange(
            nominal_min=0.9, nominal_max=1.1,
            warning_low=0.7, warning_high=1.3,
            critical_low=0.5, critical_high=1.5,
            unit="bar",
        ),
        "power_draw": TagRange(
            nominal_min=18.0, nominal_max=25.0,
            warning_low=14.0, warning_high=30.0,
            critical_low=10.0, critical_high=35.0,
            unit="kW",
        ),
    },
}
