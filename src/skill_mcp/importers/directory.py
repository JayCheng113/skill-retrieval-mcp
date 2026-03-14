"""DirectoryImporter: imports skills from a directory tree of SKILL.md files."""

from __future__ import annotations

from pathlib import Path

import yaml

from skill_mcp.importers.frontmatter import split_frontmatter
from skill_mcp.schema import Skill, SkillSource
from skill_mcp.store import ImportStats, SkillStore


class DirectoryImporter:
    """Walks a directory tree looking for SKILL.md files and imports them."""

    def import_skills(self, source_path: Path, store: SkillStore) -> ImportStats:
        skills: list[Skill] = []
        for skill_file in source_path.rglob("SKILL.md"):
            skill = self._parse_skill_file(skill_file)
            if skill is not None:
                skills.append(skill)
        return store.add_skills(skills)

    def _parse_skill_file(self, path: Path) -> Skill | None:
        text = path.read_text(encoding="utf-8")
        frontmatter, body = split_frontmatter(text)
        if frontmatter is None:
            return None

        meta = yaml.safe_load(frontmatter)
        if not isinstance(meta, dict):
            return None

        name = meta.get("name", path.stem)
        description = meta.get("description", "")
        instructions = body.strip()
        category = path.parent.name if path.parent.name else ""

        return Skill(
            name=name,
            description=description,
            instructions=instructions,
            source=SkillSource.COMMUNITY,
            category=category,
        )
