"""
app/models/asset.py

Pure-Python asset and tag definitions.
No database dependency — used by both the simulator and the PI adapter.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence


@dataclass(frozen=True)
class TagDefinition:
    """Describes one sensor tag that an asset can expose."""

    name: str          # e.g. "temperature"
    unit: str          # engineering unit string, e.g. "°C"
    description: str   # human-readable label


@dataclass(frozen=True)
class AssetDefinition:
    """Represents a physical asset in the plant."""

    asset_id: str               # e.g. "PUMP-001"
    asset_name: str             # e.g. "Cooling Water Pump"
    asset_type: str             # e.g. "pump"
    tags: Sequence[TagDefinition]

    def tag_names(self) -> list[str]:
        return [t.name for t in self.tags]

    def get_tag(self, name: str) -> TagDefinition | None:
        for tag in self.tags:
            if tag.name == name:
                return tag
        return None
