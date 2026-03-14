"""AnthropicImporter: imports skills from Anthropic's official skills repo."""

from __future__ import annotations

from pathlib import Path

import yaml

from skill_mcp.schema import Skill, SkillSource
from skill_mcp.store import ImportStats, SkillStore

ANTHROPIC_CATEGORIES: dict[str, str] = {
    "Creative & Design": "Creative & Design",
    "Development & Technical": "Development & Technical",
    "Enterprise & Communication": "Enterprise & Communication",
    "Document Skills": "Document Skills",
}


class AnthropicImporter:
    """Import skills from Anthropic's official skills repository."""

    def import_skills(self, source_path: Path, store: SkillStore) -> ImportStats:
        skills: list[Skill] = []
        for skill_file in source_path.rglob("SKILL.md"):
            skill = self._parse_skill_file(skill_file, source_path)
            if skill is not None:
                skills.append(skill)
        return store.add_skills(skills)

    def _parse_skill_file(self, path: Path, root: Path) -> Skill | None:
        text = path.read_text(encoding="utf-8")
        frontmatter, body = self._split_frontmatter(text)
        if frontmatter is None:
            return None

        meta = yaml.safe_load(frontmatter)
        if not isinstance(meta, dict):
            return None

        name = meta.get("name", path.stem)
        description = meta.get("description", "")
        instructions = body.strip()
        category = self._detect_category(path, root)

        tags: list[str] = meta.get("tags", [])
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]

        return Skill(
            name=name,
            description=description,
            instructions=instructions,
            source=SkillSource.ANTHROPIC,
            category=category,
            tags=tags,
        )

    def _detect_category(self, path: Path, root: Path) -> str:
        try:
            relative = path.parent.relative_to(root)
        except ValueError:
            return path.parent.name

        parts = relative.parts
        for part in parts:
            if part in ANTHROPIC_CATEGORIES:
                return ANTHROPIC_CATEGORIES[part]
        return path.parent.name if path.parent != root else ""

    @staticmethod
    def _split_frontmatter(text: str) -> tuple[str | None, str]:
        stripped = text.strip()
        if not stripped.startswith("---"):
            return None, text
        end_idx = stripped.find("---", 3)
        if end_idx == -1:
            return None, text
        frontmatter = stripped[3:end_idx].strip()
        body = stripped[end_idx + 3:]
        return frontmatter, body
