"""Deduplication utility for skills."""

from __future__ import annotations

from skill_mcp.schema import Skill, SkillSource

# Higher number = higher priority
_SOURCE_PRIORITY: dict[SkillSource, int] = {
    SkillSource.ANTHROPIC: 3,
    SkillSource.COMMUNITY: 2,
    SkillSource.LANGSKILLS: 1,
}


def deduplicate_skills(skills: list[Skill]) -> list[Skill]:
    """Remove exact content_hash duplicates, keeping the highest-priority source."""
    best: dict[str, Skill] = {}
    for skill in skills:
        existing = best.get(skill.content_hash)
        if existing is None:
            best[skill.content_hash] = skill
        else:
            existing_pri = _SOURCE_PRIORITY.get(existing.source, 0)
            new_pri = _SOURCE_PRIORITY.get(skill.source, 0)
            if new_pri > existing_pri:
                best[skill.content_hash] = skill
    return list(best.values())
