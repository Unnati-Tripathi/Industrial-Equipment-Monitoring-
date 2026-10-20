"""
app/config.py

Central application settings loaded from environment variables (or a .env file).

Pydantic Settings is used so that:
  - Every setting has an explicit type and default.
  - Missing required secrets surface as a clear error at startup.
  - Tests can override individual settings by passing kwargs to Settings().

The singleton `get_settings()` is cached with @lru_cache so the .env file is
read once and re-used across the application.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application ──────────────────────────────────────────────────────────
    data_source: Literal["demo", "pi"] = Field("demo", description="demo | pi")
    log_level: str = Field("INFO")
    secret_key: str = Field("change-me-in-production")

    # ── Database ─────────────────────────────────────────────────────────────
    database_url: str = Field(
        "postgresql+asyncpg://northstar:northstar@localhost:5432/northstar",
        description="Async SQLAlchemy URL.  Use 'sqlite+aiosqlite:///./dev.db' for local dev without Postgres.",
    )

    # ── Simulator ─────────────────────────────────────────────────────────────
    sim_seed: int = Field(42)
    sim_scenario: str = Field("normal")
    sim_poll_interval: int = Field(5, description="Seconds between generated measurements")

    # ── PI Web API ─────────────────────────────────────────────────────────────
    pi_base_url: str = Field("", description="PI Web API base URL, e.g. https://pi-server/piwebapi")
    pi_username: str = Field("")
    pi_password: str = Field("")
    pi_verify_ssl: bool = Field(True)
    pi_timeout_seconds: int = Field(30)

    @field_validator("sim_scenario")
    @classmethod
    def valid_scenario(cls, v: str) -> str:
        valid = {"normal", "pump_overheat", "motor_vibration", "comp_pressure", "sensor_fault"}
        if v not in valid:
            raise ValueError(f"sim_scenario must be one of {valid}, got '{v}'")
        return v

    @property
    def is_demo_mode(self) -> bool:
        return self.data_source == "demo"

    @property
    def pi_configured(self) -> bool:
        """True when PI credentials have been provided in environment."""
        return bool(self.pi_base_url and self.pi_username and self.pi_password)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached application settings singleton."""
    return Settings()
