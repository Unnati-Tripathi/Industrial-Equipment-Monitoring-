"""
app/models/measurement.py

Pydantic schema for a single timestamped sensor reading.

Design notes:
- DataQuality mirrors OSIsoft PI System quality codes (Good / Uncertain / Bad / No Data).
  Using the same vocabulary makes it easier to discuss data quality in an interview
  context and simplifies future PI adapter integration.
- DataSource distinguishes generated demo data from real PI data so the UI and
  database can always show the operator where a reading came from.
- value is Optional[float] because a BAD or NO_DATA reading has no numeric value.
- Timestamps are always UTC; the validator rejects naive datetimes to prevent
  accidental timezone bugs.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class DataQuality(str, Enum):
    """
    Sensor reading quality codes.

    GOOD      – value is reliable and within normal instrument range.
    UNCERTAIN – value may be valid but instrument health is questionable (e.g. recent
                calibration failure, communication glitch resolved).
    BAD       – instrument reported an error; value should not be used for decisions.
    NO_DATA   – no measurement was received within the expected polling window.
    """

    GOOD = "GOOD"
    UNCERTAIN = "UNCERTAIN"
    BAD = "BAD"
    NO_DATA = "NO_DATA"


class DataSource(str, Enum):
    """Where this measurement originated."""

    SIMULATED = "SIMULATED"   # produced by the local simulator
    PI_SYSTEM = "PI_SYSTEM"   # read from AVEVA PI Web API
    MANUAL = "MANUAL"         # entered by an operator


class Measurement(BaseModel):
    """
    One timestamped reading from a single sensor tag.

    All fields are validated on construction so that downstream code (alert engine,
    persistence layer) can trust the data contract without re-checking.
    """

    asset_id: str = Field(..., description="Asset identifier, e.g. PUMP-001")
    asset_name: str = Field(..., description="Human-readable asset name")
    tag_name: str = Field(..., description="Measurement tag, e.g. temperature")
    unit: str = Field(..., description="Engineering unit string, e.g. °C")

    # value is None for BAD / NO_DATA quality readings
    value: Optional[float] = Field(None, description="Numeric sensor reading")

    quality: DataQuality = Field(DataQuality.GOOD)
    source: DataSource = Field(DataSource.SIMULATED)

    # Must always be UTC-aware
    timestamp: datetime = Field(
        ..., description="UTC timestamp of the measurement"
    )

    # Optional PI tag path for traceability when source == PI_SYSTEM
    pi_tag_path: Optional[str] = Field(
        None, description="Full PI tag path, e.g. \\\\SERVER\\PUMP-001.Temperature"
    )

    model_config = {"frozen": True}

    @field_validator("timestamp")
    @classmethod
    def must_be_utc(cls, v: datetime) -> datetime:
        """Reject naive datetimes; they would silently produce wrong comparisons."""
        if v.tzinfo is None:
            raise ValueError(
                "Measurement timestamp must be timezone-aware (UTC). "
                "Use datetime.now(timezone.utc) or attach tzinfo=timezone.utc."
            )
        # Normalise to UTC so comparisons are unambiguous
        return v.astimezone(timezone.utc)

    @model_validator(mode="after")
    def value_consistent_with_quality(self) -> "Measurement":
        """
        A GOOD or UNCERTAIN reading must have a numeric value.
        BAD and NO_DATA readings should not have a value (they carry None).

        This rule is enforced as a warning-style validator: we convert a
        good-quality reading that mistakenly carries None to UNCERTAIN so that
        downstream code always knows a None value implies degraded quality.
        """
        if self.quality in (DataQuality.GOOD, DataQuality.UNCERTAIN) and self.value is None:
            # Use object.__setattr__ because the model is frozen
            object.__setattr__(self, "quality", DataQuality.UNCERTAIN)
        return self

    def is_valid_reading(self) -> bool:
        """True when the value can be used for alerting and trend analysis."""
        return self.quality in (DataQuality.GOOD, DataQuality.UNCERTAIN) and self.value is not None

    def __repr__(self) -> str:
        val = f"{self.value:.2f} {self.unit}" if self.value is not None else "N/A"
        return (
            f"Measurement({self.asset_id} / {self.tag_name} = {val} "
            f"[{self.quality.value}] @ {self.timestamp.isoformat()})"
        )
