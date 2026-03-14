"""Shared YAML frontmatter parser for SKILL.md files."""

from __future__ import annotations


def split_frontmatter(text: str) -> tuple[str | None, str]:
    """Split a SKILL.md file into (frontmatter, body).

    Returns (None, text) if no valid frontmatter is found.
    """
    stripped = text.strip()
    if not stripped.startswith("---"):
        return None, text
    end_idx = stripped.find("---", 3)
    if end_idx == -1:
        return None, text
    frontmatter = stripped[3:end_idx].strip()
    body = stripped[end_idx + 3:]
    return frontmatter, body
