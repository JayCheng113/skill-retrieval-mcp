"""LangSkillsImporter: imports skills from LangSkills SQLite bundles."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from skill_mcp.schema import Skill, SkillSource
from skill_mcp.store import ImportStats, SkillStore


class LangSkillsImporter:
    """Reads LangSkills SQLite bundles and imports skills."""

    def import_skills(self, source_path: Path, store: SkillStore) -> ImportStats:
        conn = sqlite3.connect(str(source_path))
        conn.row_factory = sqlite3.Row
        try:
            cur = conn.cursor()
            cur.execute("SELECT topic, content, source_url, domain, quality_score FROM skills")
            skills: list[Skill] = []
            for row in cur.fetchall():
                skill = self._row_to_skill(row)
                skills.append(skill)
            return store.add_skills(skills)
        finally:
            conn.close()

    @staticmethod
    def _row_to_skill(row: sqlite3.Row) -> Skill:
        return Skill(
            name=row["topic"],
            description=row["topic"],
            instructions=row["content"],
            source=SkillSource.LANGSKILLS,
            category=row["domain"] or "",
            metadata={
                "source_url": row["source_url"] or "",
                "quality_score": row["quality_score"],
            },
        )
