"""Tests for SkillStore."""

from skill_mcp.schema import Skill, SkillSource
from skill_mcp.store import SkillStore


def _make_skill(name: str = "test-skill", source: SkillSource = SkillSource.COMMUNITY) -> Skill:
    return Skill(
        name=name,
        description=f"Description for {name}",
        instructions=f"Instructions for {name}",
        source=source,
        category="testing",
    )


def test_add_and_get_skill():
    store = SkillStore()
    skill = _make_skill()
    assert store.add_skill(skill)
    assert store.count() == 1

    retrieved = store.get_skill(skill.id)
    assert retrieved is not None
    assert retrieved.name == "test-skill"
    assert retrieved.description == "Description for test-skill"
    store.close()


def test_search_keyword():
    store = SkillStore()
    store.add_skill(_make_skill("debug-memory"))
    store.add_skill(_make_skill("write-tests"))

    results = store.search_keyword("debug")
    assert len(results) >= 1
    assert results[0].name == "debug-memory"
    store.close()


def test_search_keyword_bad_syntax():
    store = SkillStore()
    store.add_skill(_make_skill("test-skill"))
    # Should not raise even with bad FTS5 syntax
    results = store.search_keyword('"unclosed quote')
    assert isinstance(results, list)
    store.close()


def test_category_counts():
    store = SkillStore()
    store.add_skill(_make_skill("s1"))
    store.add_skill(_make_skill("s2"))

    counts = store.category_counts()
    assert len(counts) == 1
    assert counts[0]["category"] == "testing"
    assert counts[0]["count"] == 2
    store.close()


def test_dedup_higher_priority_replaces():
    store = SkillStore()
    s1 = Skill(
        name="s1", description="d", instructions="same content",
        source=SkillSource.LANGSKILLS,
    )
    store.add_skill(s1)
    assert store.count() == 1

    s2 = Skill(
        name="s2", description="d", instructions="same content",
        source=SkillSource.ANTHROPIC,
    )
    assert store.add_skill(s2)
    assert store.count() == 1  # replaced, not added
    remaining = store.get_all()[0]
    assert remaining.source == SkillSource.ANTHROPIC
    store.close()


def test_dedup_lower_priority_rejected():
    store = SkillStore()
    s1 = Skill(
        name="s1", description="d", instructions="same content",
        source=SkillSource.ANTHROPIC,
    )
    store.add_skill(s1)

    s2 = Skill(
        name="s2", description="d", instructions="same content",
        source=SkillSource.LANGSKILLS,
    )
    assert not store.add_skill(s2)
    assert store.count() == 1
    store.close()


def test_readonly_mode(tmp_path):
    db_path = tmp_path / "test.db"
    # Create and populate
    store = SkillStore(db_path)
    store.add_skill(_make_skill())
    store.close()

    # Open readonly
    ro_store = SkillStore(db_path, readonly=True)
    assert ro_store.count() == 1
    assert ro_store.get_skill(ro_store.get_all()[0].id) is not None
    ro_store.close()
