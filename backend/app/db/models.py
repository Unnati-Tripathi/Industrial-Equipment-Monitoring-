"""
app/db/models.py

SQLAlchemy ORM models for application persistence.

Tables
──────
assets          – plant asset catalogue (PUMP-001, MOTOR-001, COMP-001)
tags            – sensor tag definitions belonging to an asset
measurements    – timestamped sensor readings (both simulated and PI)
alerts          – threshold violations (implemented in Phase 3)

Design decisions
────────────────
• `asset_id` / `tag_name` are natural string keys (e.g. "PUMP-001", "temperature").
  Surrogate integer PKs are used internally for FK efficiency, but the natural
  keys are enforced as UNIQUE and indexed for fast lookups.

• `data_source` is stored as a plain VARCHAR string (matching the DataSource enum)
  rather than a DB enum type.  This avoids Postgres-specific ALTER TABLE operations
  when adding a new source in the future.

• Timestamps are stored as `TIMESTAMP WITH TIME ZONE` (mapped to `DateTime(timezone=True)`)
  so the database always stores UTC.  Application code must always supply UTC-aware
  datetimes — enforced by the Measurement Pydantic model.

• `value` is nullable because BAD / NO_DATA quality readings have no numeric value.

• Indexes are created on the columns most commonly used in WHERE clauses:
    - (asset_id, tag_name, timestamp) for historical queries
    - (timestamp) for time-range scans
    - (quality) for filtering bad readings
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class AssetORM(Base):
    __tablename__ = "assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)
    asset_name: Mapped[str] = mapped_column(String(128), nullable=False)
    asset_type: Mapped[str] = mapped_column(String(64), nullable=False)

    tags: Mapped[list["TagORM"]] = relationship(
        "TagORM", back_populates="asset", cascade="all, delete-orphan"
    )
    measurements: Mapped[list["MeasurementORM"]] = relationship(
        "MeasurementORM", back_populates="asset", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Asset {self.asset_id} ({self.asset_type})>"


class TagORM(Base):
    __tablename__ = "tags"
    __table_args__ = (
        UniqueConstraint("asset_id", "tag_name", name="uq_asset_tag"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("assets.asset_id", ondelete="CASCADE"), nullable=False, index=True
    )
    tag_name: Mapped[str] = mapped_column(String(64), nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str] = mapped_column(String(256), nullable=False, default="")

    asset: Mapped["AssetORM"] = relationship("AssetORM", back_populates="tags")

    def __repr__(self) -> str:
        return f"<Tag {self.asset_id}/{self.tag_name} [{self.unit}]>"


class MeasurementORM(Base):
    __tablename__ = "measurements"
    __table_args__ = (
        # Primary access pattern: "give me all readings for PUMP-001/temperature
        #  between T1 and T2 ordered by time"
        Index("ix_measurements_asset_tag_time", "asset_id", "tag_name", "timestamp"),
        # Secondary: time-range scans across all assets (dashboard refresh)
        Index("ix_measurements_timestamp", "timestamp"),
        # Filter: exclude BAD / NO_DATA quickly
        Index("ix_measurements_quality", "quality"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Denormalised asset_id and tag_name for query performance.
    # The FK to assets ensures referential integrity without requiring a JOIN
    # every time we look up measurements.
    asset_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("assets.asset_id", ondelete="CASCADE"), nullable=False
    )
    asset_name: Mapped[str] = mapped_column(String(128), nullable=False)
    tag_name: Mapped[str] = mapped_column(String(64), nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)

    value: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Stored as VARCHAR matching DataQuality enum values: GOOD/UNCERTAIN/BAD/NO_DATA
    quality: Mapped[str] = mapped_column(String(16), nullable=False, default="GOOD")

    # Stored as VARCHAR matching DataSource enum values: SIMULATED/PI_SYSTEM/MANUAL
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="SIMULATED")

    # Always UTC.  `timezone=True` instructs SQLAlchemy to use TIMESTAMPTZ in Postgres.
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Optional PI tag path for traceability when source == PI_SYSTEM
    pi_tag_path: Mapped[str | None] = mapped_column(String(512), nullable=True)

    asset: Mapped["AssetORM"] = relationship("AssetORM", back_populates="measurements")

    def __repr__(self) -> str:
        val = f"{self.value:.3f} {self.unit}" if self.value is not None else "N/A"
        return f"<Measurement {self.asset_id}/{self.tag_name}={val} [{self.quality}] @ {self.timestamp}>"


class AlertORM(Base):
    """
    Placeholder table for Phase 3.  Defined here so that the initial Alembic
    migration creates it — avoids a second migration just to add the table.
    """
    __tablename__ = "alerts"
    __table_args__ = (
        Index("ix_alerts_asset_tag", "asset_id", "tag_name"),
        Index("ix_alerts_status", "status"),
        Index("ix_alerts_triggered_at", "triggered_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("assets.asset_id", ondelete="CASCADE"), nullable=False
    )
    asset_name: Mapped[str] = mapped_column(String(128), nullable=False)
    tag_name: Mapped[str] = mapped_column(String(64), nullable=False)

    observed_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    threshold_value: Mapped[float] = mapped_column(Float, nullable=False)
    threshold_direction: Mapped[str] = mapped_column(String(8), nullable=False)  # "high" | "low"
    severity: Mapped[str] = mapped_column(String(16), nullable=False)            # "warning" | "critical"

    # Status: "active" | "resolved"
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")

    triggered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Human-readable explanation for the operator
    explanation: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # Source of the measurement that triggered the alert
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="SIMULATED")

    # Prevent duplicate alert creation: True when this alert is the "active" representative
    # for a continuous fault.  Only one active alert per (asset_id, tag_name, severity).
    is_representative: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    def __repr__(self) -> str:
        return (
            f"<Alert {self.asset_id}/{self.tag_name} [{self.severity}] "
            f"status={self.status} @ {self.triggered_at}>"
        )
