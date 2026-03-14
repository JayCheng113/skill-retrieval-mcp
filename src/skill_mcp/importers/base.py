"""Base importer protocol for skill sources."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from skill_mcp.store import ImportStats, SkillStore


class BaseImporter(Protocol):
    """Protocol that all skill importers must implement."""

    def import_skills(self, source_path: Path, store: SkillStore) -> ImportStats: ...
