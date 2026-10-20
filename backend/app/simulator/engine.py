"""
app/simulator/engine.py

Deterministic measurement generator for Northstar Components.

Design rationale
────────────────
• Uses random.Random(seed) — a local PRNG instance — so the global random state
  is never touched.  Multiple SimulatorEngine instances with the same seed always
  produce identical output regardless of import order.

• generate_batch() produces measurements for *all* tags on *all* assets in one
  call, grouped by time-step.  This makes it easy to persist a consistent
  snapshot for a given instant.

• Fault scenarios inject drift and noise via TagPerturbation objects defined in
  scenarios.py.  The engine does not contain scenario logic; it only reads
  perturbation parameters.  New scenarios can be added without touching this file.

• Values are clamped to ±50 % of the critical range to avoid generating
  physically impossible numbers (e.g. negative pressure).  The clamp is
  documented rather than silent.

Run as a script to print sample output:
    python -m app.simulator.engine
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import Iterator

from app.models.measurement import DataQuality, DataSource, Measurement
from app.simulator.assets import ASSET_REGISTRY
from app.simulator.ranges import OPERATING_RANGES
from app.simulator.scenarios import ScenarioConfig, TagPerturbation


# Noise amplitude as a fraction of the nominal range width.
# e.g. a range of 30 °C with this factor → ±1.5 °C std dev of baseline noise.
_NOISE_FRACTION = 0.05


class SimulatorEngine:
    """
    Produces time-ordered Measurement objects for all plant assets.

    Parameters
    ----------
    scenario : ScenarioConfig
        Describes which tags to perturb and by how much.
    seed : int
        PRNG seed.  Same seed + scenario always produces the same stream.
    start_time : datetime | None
        First measurement timestamp (UTC-aware).  Defaults to current UTC time.
    """

    def __init__(
        self,
        scenario: ScenarioConfig,
        seed: int = 42,
        start_time: datetime | None = None,
    ) -> None:
        self.scenario = scenario
        self._rng = random.Random(seed)
        self._start_time: datetime = start_time or datetime.now(timezone.utc)

        # Running value per (asset_id, tag_name) — tracks cumulative drift
        self._state: dict[tuple[str, str], float] = {}
        self._initialise_state()

    # ──────────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────────

    def generate_batch(
        self,
        n_steps: int = 1,
        interval_seconds: int = 5,
    ) -> list[Measurement]:
        """
        Generate n_steps polling cycles worth of measurements.

        Returns a flat list ordered by timestamp then asset_id then tag_name.
        All assets and all their tags are produced for every step.
        """
        results: list[Measurement] = []
        for step in range(n_steps):
            ts = self._start_time + timedelta(seconds=step * interval_seconds)
            for asset_id, asset_def in ASSET_REGISTRY.items():
                for tag_def in asset_def.tags:
                    m = self._generate_one(asset_id, asset_def.asset_name, tag_def.name, tag_def.unit, ts)
                    results.append(m)
        # Advance the engine's concept of "now" so subsequent calls continue the timeline
        self._start_time += timedelta(seconds=n_steps * interval_seconds)
        return results

    def stream(self, interval_seconds: int = 5) -> Iterator[list[Measurement]]:
        """
        Infinite generator — yields one full-plant snapshot per iteration.

        Useful for the background polling task in Phase 4+.
        """
        while True:
            yield self.generate_batch(n_steps=1, interval_seconds=interval_seconds)

    # ──────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ──────────────────────────────────────────────────────────────────────

    def _initialise_state(self) -> None:
        """
        Set starting values for every tag on every asset.

        We start at the midpoint of the nominal range, with a small random
        perturbation so different seeds start at slightly different values —
        making the demo look more realistic on the first frame.
        """
        for asset_id, asset_def in ASSET_REGISTRY.items():
            ranges = OPERATING_RANGES.get(asset_id, {})
            for tag_def in asset_def.tags:
                r = ranges.get(tag_def.name)
                if r is None:
                    # Fallback: should not happen with a consistent registry,
                    # but guard defensively.
                    self._state[(asset_id, tag_def.name)] = 0.0
                    continue
                midpoint = (r.nominal_min + r.nominal_max) / 2.0
                jitter_range = (r.nominal_max - r.nominal_min) * 0.1
                self._state[(asset_id, tag_def.name)] = (
                    midpoint + self._rng.uniform(-jitter_range, jitter_range)
                )

    def _generate_one(
        self,
        asset_id: str,
        asset_name: str,
        tag_name: str,
        unit: str,
        timestamp: datetime,
    ) -> Measurement:
        """Produce a single Measurement for one (asset, tag) at a given timestamp."""
        perturbation: TagPerturbation = self.scenario.get_perturbation(asset_id, tag_name)

        # ── Fault quality override ─────────────────────────────────────────
        if perturbation.fault_probability > 0.0:
            if self._rng.random() < perturbation.fault_probability:
                quality_choice = self._rng.choice([DataQuality.BAD, DataQuality.NO_DATA])
                return Measurement(
                    asset_id=asset_id,
                    asset_name=asset_name,
                    tag_name=tag_name,
                    unit=unit,
                    value=None,
                    quality=quality_choice,
                    source=DataSource.SIMULATED,
                    timestamp=timestamp,
                )

        # ── Retrieve current state ─────────────────────────────────────────
        state_key = (asset_id, tag_name)
        current_value = self._state.get(state_key, 0.0)

        # ── Apply scenario drift ───────────────────────────────────────────
        current_value += perturbation.drift_rate

        # ── Baseline Gaussian noise ────────────────────────────────────────
        r = OPERATING_RANGES.get(asset_id, {}).get(tag_name)
        if r is not None:
            nominal_range = r.nominal_max - r.nominal_min
            noise_std = nominal_range * _NOISE_FRACTION * perturbation.noise_scale
            current_value += self._rng.gauss(0.0, noise_std)

            # Add scenario fixed offset (applied once per reading, not accumulated)
            reading_value = current_value + perturbation.fixed_offset

            # Clamp to a physically reasonable range (critical boundaries ± 50%)
            # This prevents values like -50 °C for an exhaust temperature.
            half_critical = (r.critical_high - r.critical_low) * 0.5
            lower_bound = r.critical_low - half_critical
            upper_bound = r.critical_high + half_critical
            reading_value = max(lower_bound, min(upper_bound, reading_value))
        else:
            reading_value = current_value

        # ── Persist updated state (drift accumulates, offset does not) ─────
        self._state[state_key] = current_value

        # ── Determine quality from position in operating ranges ────────────
        quality = _value_quality(reading_value, r) if r else DataQuality.UNCERTAIN

        return Measurement(
            asset_id=asset_id,
            asset_name=asset_name,
            tag_name=tag_name,
            unit=unit,
            value=round(reading_value, 4),
            quality=quality,
            source=DataSource.SIMULATED,
            timestamp=timestamp,
        )


def _value_quality(value: float, r) -> DataQuality:  # r: TagRange
    """
    Map a numeric value to a DataQuality based on operating range thresholds.

    GOOD       – within nominal_min … nominal_max
    UNCERTAIN  – outside nominal but within warning limits
    BAD        – outside warning limits (or beyond critical limits)
    """
    if r.nominal_min <= value <= r.nominal_max:
        return DataQuality.GOOD
    if r.warning_low <= value <= r.warning_high:
        return DataQuality.UNCERTAIN
    # Outside warning limits → BAD (still a numeric value, just alarming)
    return DataQuality.BAD


# ──────────────────────────────────────────────────────────────────────────────
# CLI smoke test
# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import json
    from app.simulator.scenarios import SCENARIOS

    print("=" * 70)
    print("Northstar Simulator — smoke test (10 steps per scenario)")
    print("=" * 70)

    for scenario_name, scenario in SCENARIOS.items():
        print(f"\n── Scenario: {scenario_name} ──────────────────────────────────")
        engine = SimulatorEngine(scenario=scenario, seed=42)
        batch = engine.generate_batch(n_steps=3, interval_seconds=5)
        for m in batch[:6]:  # print first 6 readings only to keep output readable
            val = f"{m.value:.2f} {m.unit}" if m.value is not None else "N/A"
            print(f"  {m.timestamp.strftime('%H:%M:%S')}  {m.asset_id:10s}  {m.tag_name:20s}  {val:15s}  [{m.quality.value}]")
