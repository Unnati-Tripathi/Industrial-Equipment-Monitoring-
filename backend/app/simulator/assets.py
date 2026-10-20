"""
app/simulator/assets.py

Asset registry for Northstar Components plant.

Each AssetDefinition lists only the sensors that physically exist on that machine.
Assigning a temperature tag to the compressor when the compressor has no temperature
sensor would produce misleading data, so the list is explicit and limited.

Engineering decisions documented here are intentionally kept simple so they can be
explained in an interview without referencing a real plant P&ID.
"""
from __future__ import annotations

from app.models.asset import AssetDefinition, TagDefinition

# ── PUMP-001 – Cooling Water Pump ────────────────────────────────────────────
# A centrifugal pump circulating cooling water.  Sensors: bearing temperature,
# flow rate, suction (inlet) pressure, discharge (outlet) pressure.
PUMP_001 = AssetDefinition(
    asset_id="PUMP-001",
    asset_name="Cooling Water Pump",
    asset_type="pump",
    tags=[
        TagDefinition("temperature",     "°C",   "Bearing temperature"),
        TagDefinition("flow_rate",       "m³/h", "Volumetric flow rate"),
        TagDefinition("inlet_pressure",  "bar",  "Suction-side pressure"),
        TagDefinition("outlet_pressure", "bar",  "Discharge-side pressure"),
    ],
)

# ── MOTOR-001 – Main Drive Motor ─────────────────────────────────────────────
# An AC induction motor driving a production line conveyor.
# Sensors: winding temperature, vibration (radial velocity RMS), line current, speed.
MOTOR_001 = AssetDefinition(
    asset_id="MOTOR-001",
    asset_name="Main Drive Motor",
    asset_type="motor",
    tags=[
        TagDefinition("temperature", "°C",   "Winding temperature"),
        TagDefinition("vibration",   "mm/s", "Radial vibration velocity (RMS)"),
        TagDefinition("current",     "A",    "Line current (phase A)"),
        TagDefinition("rpm",         "RPM",  "Shaft speed"),
    ],
)

# ── COMP-001 – Air Compressor ─────────────────────────────────────────────────
# A reciprocating air compressor supplying the plant pneumatic system.
# Sensors: discharge temperature, discharge pressure, inlet pressure, power draw.
COMP_001 = AssetDefinition(
    asset_id="COMP-001",
    asset_name="Air Compressor",
    asset_type="compressor",
    tags=[
        TagDefinition("temperature",       "°C",  "Discharge temperature"),
        TagDefinition("discharge_pressure","bar",  "Discharge (outlet) pressure"),
        TagDefinition("inlet_pressure",    "bar",  "Inlet (suction) pressure"),
        TagDefinition("power_draw",        "kW",   "Active power consumption"),
    ],
)

# Registry used by simulator engine and alert engine to look up assets by ID
ASSET_REGISTRY: dict[str, AssetDefinition] = {
    PUMP_001.asset_id: PUMP_001,
    MOTOR_001.asset_id: MOTOR_001,
    COMP_001.asset_id: COMP_001,
}
