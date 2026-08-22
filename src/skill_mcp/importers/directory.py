"""DirectoryImporter: imports skills from a directory tree of SKILL.md files."""

from __future__ import annotations

import logging
from pathlib import Path

from skill_mcp.importers.frontmatter import parse_frontmatter, split_frontmatter
from skill_mcp.schema import Skill, SkillSource
from skill_mcp.store import ImportStats, SkillStore

logger = logging.getLogger("skill_mcp")


class DirectoryImporter:
    """Walks a directory tree looking for SKILL.md files and imports them."""

    def import_skills(self, source_path: Path, store: SkillStore) -> ImportStats:
        skills: list[Skill] = []
        for skill_file in sorted(source_path.rglob("SKILL.md")):
            # One malformed file must not abort the remaining hundreds.
            try:
                skill = self._parse_skill_file(skill_file, source_path)
            except Exception:
                logger.warning("Skipping unparseable skill file: %s", skill_file, exc_info=True)
                continue
            if skill is not None:
                skills.append(skill)
        return store.add_skills(skills)

    def _parse_skill_file(self, path: Path, root: Path) -> Skill | None:
        text = path.read_text(encoding="utf-8", errors="replace")
        frontmatter, body = split_frontmatter(text)
        if frontmatter is None:
            logger.warning("Skipping %s: no frontmatter", path)
            return None

        meta = parse_frontmatter(frontmatter)
        if not meta:
            logger.warning("Skipping %s: unrecoverable frontmatter", path)
            return None

        name = str(meta.get("name") or path.parent.name)
        description = str(meta.get("description") or "").strip()

        tags = meta.get("tags", [])
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]
        elif not isinstance(tags, list):
            tags = []

        return Skill(
            name=name,
            description=description,
            instructions=body.strip(),
            source=SkillSource.COMMUNITY,
            category=self._category(path, root),
            tags=[str(t) for t in tags],
        )

    @staticmethod
    def _category(path: Path, root: Path) -> str:
        """Grouping folders between the root and the skill's own folder.

        `root/<skill>/SKILL.md` has no grouping level, so no category —
        the old `path.parent.name` labelled every skill with its own name.
        """
        try:
            relative = path.parent.relative_to(root)
        except ValueError:
            return ""
        return relative.parts[0] if len(relative.parts) > 1 else ""
