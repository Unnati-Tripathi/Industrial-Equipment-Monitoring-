"""initial_schema

Revision ID: 4aa756d14e6b
Revises:
Create Date: 2024-01-15 08:00:00.000000

Creates all tables for the Northstar application:
  - assets
  - tags
  - measurements
  - alerts

This migration is written by hand because the live database was not available
during development.  It matches the ORM models in app/db/models.py exactly.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic
revision: str = "4aa756d14e6b"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # ── assets ────────────────────────────────────────────────────────────────
    op.create_table(
        "assets",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("asset_id", sa.String(32), nullable=False),
        sa.Column("asset_name", sa.String(128), nullable=False),
        sa.Column("asset_type", sa.String(64), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("asset_id"),
    )
    op.create_index("ix_assets_asset_id", "assets", ["asset_id"], unique=True)

    # ── tags ──────────────────────────────────────────────────────────────────
    op.create_table(
        "tags",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("asset_id", sa.String(32), nullable=False),
        sa.Column("tag_name", sa.String(64), nullable=False),
        sa.Column("unit", sa.String(32), nullable=False),
        sa.Column("description", sa.String(256), nullable=False, server_default=""),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.asset_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("asset_id", "tag_name", name="uq_asset_tag"),
    )
    op.create_index("ix_tags_asset_id", "tags", ["asset_id"])

    # ── measurements ──────────────────────────────────────────────────────────
    op.create_table(
        "measurements",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("asset_id", sa.String(32), nullable=False),
        sa.Column("asset_name", sa.String(128), nullable=False),
        sa.Column("tag_name", sa.String(64), nullable=False),
        sa.Column("unit", sa.String(32), nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("quality", sa.String(16), nullable=False, server_default="GOOD"),
        sa.Column("source", sa.String(16), nullable=False, server_default="SIMULATED"),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("pi_tag_path", sa.String(512), nullable=True),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.asset_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_measurements_asset_tag_time",
        "measurements",
        ["asset_id", "tag_name", "timestamp"],
    )
    op.create_index("ix_measurements_timestamp", "measurements", ["timestamp"])
    op.create_index("ix_measurements_quality", "measurements", ["quality"])

    # ── alerts ────────────────────────────────────────────────────────────────
    op.create_table(
        "alerts",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("asset_id", sa.String(32), nullable=False),
        sa.Column("asset_name", sa.String(128), nullable=False),
        sa.Column("tag_name", sa.String(64), nullable=False),
        sa.Column("observed_value", sa.Float(), nullable=True),
        sa.Column("threshold_value", sa.Float(), nullable=False),
        sa.Column("threshold_direction", sa.String(8), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("triggered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("explanation", sa.Text(), nullable=False, server_default=""),
        sa.Column("source", sa.String(16), nullable=False, server_default="SIMULATED"),
        sa.Column("is_representative", sa.Boolean(), nullable=False, server_default="true"),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.asset_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_alerts_asset_tag", "alerts", ["asset_id", "tag_name"])
    op.create_index("ix_alerts_status", "alerts", ["status"])
    op.create_index("ix_alerts_triggered_at", "alerts", ["triggered_at"])


def downgrade() -> None:
    op.drop_table("alerts")
    op.drop_table("measurements")
    op.drop_table("tags")
    op.drop_table("assets")
