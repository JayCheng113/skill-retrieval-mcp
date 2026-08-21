"""Tests for CuratedImporter's licence provenance guarantees."""

import pytest

from skill_mcp.importers.curated import CURATED_REPOS, CuratedImporter, UnvettedRepositoryError
from skill_mcp.store import SkillStore

SKILL_MD = """---
name: {name}
description: A skill for {name}
---

# {name}

Do the thing.
"""


def _write_skill(root, slug: str, relative: str, name: str) -> None:
    path = root / slug / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(SKILL_MD.format(name=name), encoding="utf-8")


def test_unvetted_repository_aborts_the_import(tmp_path):
    """An unlisted repo must fail loudly, not be imported under a guessed licence."""
    _write_skill(tmp_path, "obra/superpowers", "skills/brainstorming/SKILL.md", "brainstorming")
    _write_skill(tmp_path, "somebody/scraped-skills", "skills/whatever/SKILL.md", "whatever")

    store = SkillStore()
    with pytest.raises(UnvettedRepositoryError, match="somebody/scraped-skills"):
        CuratedImporter().import_skills(tmp_path, store)

    assert store.count() == 0, "nothing may land when any source is unvetted"
    store.close()


def test_every_imported_skill_carries_a_licence_and_upstream_url(tmp_path):
    """Redistribution requires per-row attribution, so no row may lack it."""
    _write_skill(tmp_path, "obra/superpowers", "skills/brainstorming/SKILL.md", "brainstorming")
    _write_skill(tmp_path, "google/skills", "skills/cloud/gke-basics/SKILL.md", "gke-basics")

    store = SkillStore()
    CuratedImporter().import_skills(tmp_path, store)

    skills = store.get_all()
    assert len(skills) == 2
    for skill in skills:
        assert skill.metadata["license"], f"{skill.name} has no licence"
        assert skill.metadata["repo"] in CURATED_REPOS
        assert skill.metadata["repo_url"].startswith("https://github.com/")
        assert skill.metadata["repo"] in skill.source_id
    store.close()


def test_category_comes_from_upstream_grouping_only(tmp_path):
    """`skills/` is structural, not a category; a real grouping level is."""
    _write_skill(tmp_path, "obra/superpowers", "skills/brainstorming/SKILL.md", "brainstorming")
    _write_skill(tmp_path, "google/skills", "skills/cloud/gke-basics/SKILL.md", "gke-basics")

    store = SkillStore()
    CuratedImporter().import_skills(tmp_path, store)

    by_name = {s.name: s for s in store.get_all()}
    assert by_name["brainstorming"].category == ""
    assert by_name["gke-basics"].category == "cloud"
    store.close()
