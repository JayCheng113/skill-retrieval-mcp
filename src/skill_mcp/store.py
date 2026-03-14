"""SkillStore: SQLite-backed skill storage with FTS5 full-text search."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from skill_mcp.dedup import _SOURCE_PRIORITY
from skill_mcp.schema import Skill, SkillSource


@dataclass
class ImportStats:
    """Statistics from an import operation."""

    total: int = 0
    added: int = 0
    replaced: int = 0
    skipped_duplicate: int = 0


class SkillStore:
    """SQLite-backed skill storage with FTS5 search support."""

    def __init__(self, db_path: str | Path = ":memory:", readonly: bool = False) -> None:
        self.db_path = str(db_path)
        self.readonly = readonly
        if readonly and db_path != ":memory:":
            uri = f"file:{self.db_path}?mode=ro"
            self._conn = sqlite3.connect(uri, uri=True)
        else:
            self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        if not readonly:
            self._init_db()

    def _init_db(self) -> None:
        cur = self._conn.cursor()
        cur.executescript("""
            CREATE TABLE IF NOT EXISTS skills (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT NOT NULL,
                instructions TEXT NOT NULL,
                source TEXT NOT NULL,
                source_id TEXT DEFAULT '',
                category TEXT DEFAULT '',
                tags TEXT DEFAULT '[]',
                metadata TEXT DEFAULT '{}',
                content_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_skills_source ON skills(source);
            CREATE INDEX IF NOT EXISTS idx_skills_category ON skills(category);
            CREATE INDEX IF NOT EXISTS idx_skills_content_hash ON skills(content_hash);

            CREATE VIRTUAL TABLE IF NOT EXISTS skills_fts USING fts5(
                name, description, instructions,
                content='skills',
                content_rowid='rowid'
            );

            CREATE TRIGGER IF NOT EXISTS skills_ai AFTER INSERT ON skills BEGIN
                INSERT INTO skills_fts(rowid, name, description, instructions)
                VALUES (new.rowid, new.name, new.description, new.instructions);
            END;

            CREATE TRIGGER IF NOT EXISTS skills_ad AFTER DELETE ON skills BEGIN
                INSERT INTO skills_fts(skills_fts, rowid, name, description, instructions)
                VALUES ('delete', old.rowid, old.name, old.description, old.instructions);
            END;
        """)
        self._conn.commit()

    def add_skill(self, skill: Skill) -> bool:
        result, _ = self._add_skill_detail(skill)
        self._conn.commit()
        return result

    def _add_skill_detail(self, skill: Skill) -> tuple[bool, bool]:
        """Insert a skill, handling dedup by content_hash. Does NOT commit."""
        cur = self._conn.cursor()
        cur.execute(
            "SELECT id, source FROM skills WHERE content_hash = ?",
            (skill.content_hash,),
        )
        existing = cur.fetchone()
        replaced = False
        if existing is not None:
            existing_source = SkillSource(existing["source"])
            new_pri = _SOURCE_PRIORITY.get(skill.source, 0)
            old_pri = _SOURCE_PRIORITY.get(existing_source, 0)
            if new_pri <= old_pri:
                return False, False
            cur.execute("DELETE FROM skills WHERE id = ?", (existing["id"],))
            replaced = True

        cur.execute(
            """INSERT OR IGNORE INTO skills
            (id, name, description, instructions, source, source_id,
             category, tags, metadata, content_hash, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                skill.id,
                skill.name,
                skill.description,
                skill.instructions,
                skill.source.value,
                skill.source_id,
                skill.category,
                json.dumps(skill.tags),
                json.dumps(skill.metadata),
                skill.content_hash,
                skill.created_at.isoformat(),
            ),
        )
        success = cur.rowcount > 0
        return success, replaced and success

    def add_skills(self, skills: list[Skill]) -> ImportStats:
        stats = ImportStats(total=len(skills))
        for skill in skills:
            success, replaced = self._add_skill_detail(skill)
            if success:
                if replaced:
                    stats.replaced += 1
                else:
                    stats.added += 1
            else:
                stats.skipped_duplicate += 1
        self._conn.commit()
        return stats

    def get_skill(self, skill_id: str) -> Skill | None:
        cur = self._conn.cursor()
        cur.execute("SELECT * FROM skills WHERE id = ?", (skill_id,))
        row = cur.fetchone()
        if row is None:
            return None
        return self._row_to_skill(row)

    def search_keyword(self, query: str, limit: int = 10) -> list[Skill]:
        """Full-text search using FTS5."""
        cur = self._conn.cursor()
        try:
            cur.execute(
                """SELECT s.* FROM skills s
                JOIN skills_fts f ON s.rowid = f.rowid
                WHERE skills_fts MATCH ?
                ORDER BY rank
                LIMIT ?""",
                (query, limit),
            )
        except sqlite3.OperationalError:
            # FTS5 query syntax error — escape and retry
            escaped = '"' + query.replace('"', '""') + '"'
            cur.execute(
                """SELECT s.* FROM skills s
                JOIN skills_fts f ON s.rowid = f.rowid
                WHERE skills_fts MATCH ?
                ORDER BY rank
                LIMIT ?""",
                (escaped, limit),
            )
        return [self._row_to_skill(row) for row in cur.fetchall()]

    def get_by_category(self, category: str) -> list[Skill]:
        cur = self._conn.cursor()
        cur.execute("SELECT * FROM skills WHERE category = ?", (category,))
        return [self._row_to_skill(row) for row in cur.fetchall()]

    def get_all(self) -> list[Skill]:
        cur = self._conn.cursor()
        cur.execute("SELECT * FROM skills")
        return [self._row_to_skill(row) for row in cur.fetchall()]

    def iter_all(self) -> Iterator[Skill]:
        cur = self._conn.cursor()
        cur.execute("SELECT * FROM skills")
        for row in cur:
            yield self._row_to_skill(row)

    def all_ids(self) -> set[str]:
        """Return all skill IDs without loading full skill objects."""
        cur = self._conn.cursor()
        cur.execute("SELECT id FROM skills")
        return {row[0] for row in cur.fetchall()}

    def count(self) -> int:
        cur = self._conn.cursor()
        cur.execute("SELECT COUNT(*) FROM skills")
        return cur.fetchone()[0]

    def categories(self) -> list[str]:
        cur = self._conn.cursor()
        cur.execute("SELECT DISTINCT category FROM skills WHERE category != ''")
        return [row[0] for row in cur.fetchall()]

    def category_counts(self) -> list[dict[str, Any]]:
        """Return categories with their skill counts."""
        cur = self._conn.cursor()
        cur.execute(
            "SELECT category, COUNT(*) as count FROM skills WHERE category != '' GROUP BY category ORDER BY count DESC"
        )
        return [{"category": row[0], "count": row[1]} for row in cur.fetchall()]

    def merge_from(self, other_db: str | Path) -> ImportStats:
        """Merge all skills from another database, respecting source priority dedup.

        Streams skills from the source DB. Commits once at the end for performance.
        """
        source = SkillStore(other_db, readonly=True)
        stats = ImportStats(total=source.count())
        try:
            for skill in source.iter_all():
                success, replaced = self._add_skill_detail(skill)
                if success:
                    if replaced:
                        stats.replaced += 1
                    else:
                        stats.added += 1
                else:
                    stats.skipped_duplicate += 1
            self._conn.commit()
        finally:
            source.close()
        return stats

    def delete_skill(self, skill_id: str) -> bool:
        cur = self._conn.cursor()
        cur.execute("DELETE FROM skills WHERE id = ?", (skill_id,))
        self._conn.commit()
        return cur.rowcount > 0

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> SkillStore:
        return self

    def __exit__(self, *args) -> None:
        self.close()

    def _row_to_skill(self, row: sqlite3.Row) -> Skill:
        data = dict(row)
        return Skill.from_dict(data)
