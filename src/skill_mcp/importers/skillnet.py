"""SkillNetImporter: imports skills from SkillNet API or bulk JSON dump."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from skill_mcp.schema import Skill, SkillSource
from skill_mcp.store import ImportStats, SkillStore

SKILLNET_CATEGORIES: dict[str, str] = {
    "Development": "Development",
    "AIGC": "AIGC",
    "Research": "Research",
    "Science": "Science",
    "Business": "Business",
    "Testing": "Testing",
    "Productivity": "Productivity",
    "Security": "Security",
    "Lifestyle": "Lifestyle",
    "Other": "Other",
}

_API_BASE = "http://api-skillnet.openkg.cn/v1/search"


class SkillNetImporter:
    """Import skills from SkillNet via REST API or a bulk JSON-lines file."""

    def __init__(self, mode: str = "file") -> None:
        if mode not in ("api", "file"):
            raise ValueError(f"Invalid mode: {mode!r}. Must be 'api' or 'file'.")
        self.mode = mode

    def import_skills(self, source_path: Path, store: SkillStore) -> ImportStats:
        if self.mode == "file":
            return self._import_from_file(source_path, store)
        return self._import_from_api(store)

    def _import_from_file(self, path: Path, store: SkillStore) -> ImportStats:
        skills: list[Skill] = []
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                skill = self._parse_record(obj)
                if skill is not None:
                    skills.append(skill)
        return store.add_skills(skills)

    def _import_from_api(self, store: SkillStore) -> ImportStats:
        import urllib.request

        all_skills: list[Skill] = []
        page = 1
        page_size = 50
        while True:
            url = f"{_API_BASE}?page={page}&page_size={page_size}"
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode())
            items = data.get("data", data.get("results", []))
            if not items:
                break
            for item in items:
                skill = self._parse_record(item)
                if skill is not None:
                    all_skills.append(skill)
            page += 1
        return store.add_skills(all_skills)

    def _parse_record(self, obj: dict[str, Any]) -> Skill | None:
        name = (obj.get("name") or obj.get("skill_name", "")).strip()
        if not name:
            return None

        description = obj.get("description") or obj.get("skill_description") or ""
        instructions = (
            obj.get("instructions") or obj.get("content") or obj.get("skill_content") or ""
        )

        raw_category = obj.get("category", "")
        category = SKILLNET_CATEGORIES.get(raw_category, raw_category)

        tags = obj.get("tags", [])
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]

        metadata = obj.get("metadata", {})
        if isinstance(metadata, str):
            metadata = json.loads(metadata) if metadata else {}

        return Skill(
            name=name,
            description=description,
            instructions=instructions,
            source=SkillSource.SKILLNET,
            category=category,
            tags=tags,
            metadata=metadata,
        )
