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


def test_pyyaml_hostile_upstream_skill_still_reaches_the_corpus(tmp_path):
    """The redistributed corpus is rebuilt from upstream HEAD, which we do not control.

    An unquoted ": " in a description is a hard ScannerError, and 199 of the 2,398
    real SKILL.md files surveyed quote a description that contains one -- meaning
    their authors hit this and worked around it. The next upstream commit that
    forgets the quotes must not silently drop the skill from what we publish.
    """
    _write_skill(tmp_path, "obra/superpowers", "skills/brainstorming/SKILL.md", "brainstorming")
    hostile = tmp_path / "google/skills/skills/cloud/gke-basics/SKILL.md"
    hostile.parent.mkdir(parents=True)
    hostile.write_text(
        "---\nname: gke-basics\ndescription: Use when: the cluster needs scaling\n---\n\nBody.\n",
        encoding="utf-8",
    )

    store = SkillStore()
    CuratedImporter().import_skills(tmp_path, store)

    by_name = {s.name: s for s in store.get_all()}
    assert set(by_name) == {"brainstorming", "gke-basics"}
    assert by_name["gke-basics"].description == "Use when: the cluster needs scaling"
    assert by_name["gke-basics"].metadata["license"] == "Apache-2.0"
    store.close()


# ---------------------------------------------------------------------------
# Tolerant frontmatter (real-world SKILL.md files are not strict YAML)
# ---------------------------------------------------------------------------


def _write_plain_skill(root, name, frontmatter, body=None):
    body = body or f"## Steps for {name}\n\n1. Do the thing.\n"
    d = root / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(f"---\n{frontmatter}---\n\n{body}", encoding="utf-8")
    return d


def test_unquoted_colon_in_description_does_not_abort_import(tmp_path):
    """One PyYAML-hostile file must neither crash nor take the others down."""
    from skill_mcp.importers.directory import DirectoryImporter
    from skill_mcp.store import SkillStore

    root = tmp_path / "skills"
    _write_plain_skill(
        root,
        "blender-mcp",
        "name: blender-mcp\n"
        "description: Modeling and taste. Blender MCP server: official Blender Lab MCP at pr\n",
    )
    _write_plain_skill(root, "clean-one", "name: clean-one\ndescription: A well-formed skill\n")

    store = SkillStore(tmp_path / "store.jsonl")
    stats = DirectoryImporter().import_skills(root, store)

    assert stats.added == 2
    by_name = {s.name: s for s in store.get_all()}
    assert "official Blender Lab MCP at pr" in by_name["blender-mcp"].description
    assert by_name["clean-one"].description == "A well-formed skill"


def test_block_scalar_description_survives_salvage(tmp_path):
    from skill_mcp.importers.frontmatter import parse_frontmatter

    meta = parse_frontmatter(
        "name: x\n"
        "description: >-\n"
        "  Trigger on: SwiftUI, animation, haptic\n"
        "  and more lines here\n"
        "tags: [a, b]\n"
    )
    assert meta["name"] == "x"
    assert meta["description"] == "Trigger on: SwiftUI, animation, haptic and more lines here"
    assert meta["tags"] == ["a", "b"]


def test_dash_fence_inside_description_is_not_a_closing_fence(tmp_path):
    """The closing fence must own its whole line; `---` mid-text is content."""
    from skill_mcp.importers.frontmatter import split_frontmatter

    fm, body = split_frontmatter(
        "---\nname: x\ndescription: uses --- separators inline\n---\nBODY\n"
    )
    assert fm is not None
    assert "uses --- separators inline" in fm
    assert body.strip() == "BODY"


def test_directory_category_is_grouping_folder_not_skill_name(tmp_path):
    from skill_mcp.importers.directory import DirectoryImporter
    from skill_mcp.store import SkillStore

    root = tmp_path / "skills"
    _write_plain_skill(root, "flat-skill", "name: flat-skill\ndescription: at the root\n")
    _write_plain_skill(root / "cloud", "gke-thing", "name: gke-thing\ndescription: grouped\n")

    store = SkillStore(tmp_path / "store.jsonl")
    DirectoryImporter().import_skills(root, store)
    by_name = {s.name: s for s in store.get_all()}
    assert by_name["flat-skill"].category == ""
    assert by_name["gke-thing"].category == "cloud"


def test_frontmatter_category_outranks_directory_inference(tmp_path):
    from skill_mcp.importers.directory import DirectoryImporter
    from skill_mcp.store import SkillStore

    root = tmp_path / "skills"
    _write_plain_skill(
        root, "tagged", "name: tagged\ndescription: has explicit category\ncategory: design\n"
    )
    store = SkillStore(tmp_path / "s.jsonl")
    DirectoryImporter().import_skills(root, store)
    assert store.get_all()[0].category == "design"
