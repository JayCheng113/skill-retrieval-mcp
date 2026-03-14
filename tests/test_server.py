"""Tests for MCP server tool handlers."""

import json

import skill_mcp.server as srv
from skill_mcp.embeddings import EmbeddingModel
from skill_mcp.index import SkillIndex
from skill_mcp.schema import Skill, SkillSource
from skill_mcp.store import SkillStore


def _setup_server():
    """Set up server state for testing."""
    store = SkillStore()
    skills = [
        Skill(
            name="debug-memory",
            description="Debug memory leaks",
            instructions="Use profiler tools",
            source=SkillSource.COMMUNITY,
            category="debugging",
        ),
        Skill(
            name="write-tests",
            description="Write unit tests",
            instructions="Use pytest framework",
            source=SkillSource.COMMUNITY,
            category="testing",
        ),
    ]
    store.add_skills(skills)

    emb = EmbeddingModel(backend="mock")
    index = SkillIndex(emb.dimension)
    index.build(store, emb)

    srv._store = store
    srv._index = index
    srv._embedding = emb
    return store, skills


def test_search_skills():
    store, skills = _setup_server()
    result = srv._handle_search_skills({"query": "debug", "k": 2})
    data = json.loads(result[0].text)
    assert len(data) == 2
    assert all("id" in r and "name" in r and "score" in r for r in data)
    # Should not include instructions in search results
    assert all("instructions" not in r for r in data)
    store.close()


def test_get_skill():
    store, skills = _setup_server()
    skill_id = skills[0].id
    result = srv._handle_get_skill({"skill_id": skill_id})
    data = json.loads(result[0].text)
    assert data["name"] == "debug-memory"
    assert "instructions" in data
    assert data["instructions"] == "Use profiler tools"
    store.close()


def test_get_skill_not_found():
    store, _ = _setup_server()
    result = srv._handle_get_skill({"skill_id": "nonexistent"})
    data = json.loads(result[0].text)
    assert "error" in data
    assert data["error"] == "Skill not found"
    store.close()


def test_keyword_search():
    store, _ = _setup_server()
    result = srv._handle_keyword_search({"query": "debug", "limit": 5})
    data = json.loads(result[0].text)
    assert len(data) >= 1
    assert data[0]["name"] == "debug-memory"
    store.close()


def test_list_categories():
    store, _ = _setup_server()
    result = srv._handle_list_categories()
    data = json.loads(result[0].text)
    assert len(data) == 2
    categories = {d["category"] for d in data}
    assert "debugging" in categories
    assert "testing" in categories
    store.close()


def test_search_skills_no_index():
    store, _ = _setup_server()
    srv._index = None
    result = srv._handle_search_skills({"query": "test"})
    data = json.loads(result[0].text)
    assert "error" in data
    assert "build-index" in data["error"]
    store.close()


# ── Tool description tests ──────────────────────────────────────────


import pytest


@pytest.fixture()
def tools():
    """Fetch the tool list once."""
    import asyncio

    return asyncio.get_event_loop().run_until_complete(srv.list_tools())


def _desc(tools, name: str) -> str:
    return next(t.description for t in tools if t.name == name)


class TestToolDescriptions:
    """Tool descriptions must guide agents on WHEN to call each tool."""

    def test_search_skills_has_behavioral_trigger(self, tools):
        desc = _desc(tools, "search_skills")
        # Must tell agent when to use it
        assert "use this" in desc.lower()
        # Must reference the follow-up tool
        assert "get_skill" in desc

    def test_search_skills_no_instructions_in_results(self, tools):
        desc = _desc(tools, "search_skills")
        # Must clarify that search returns summaries only
        assert "summar" in desc.lower()

    def test_get_skill_references_workflow(self, tools):
        desc = _desc(tools, "get_skill")
        # Must mention it follows search
        assert "search_skills" in desc or "keyword_search" in desc

    def test_keyword_search_differentiates_from_semantic(self, tools):
        desc = _desc(tools, "keyword_search")
        # Must explain when to prefer keyword over semantic
        assert "keyword" in desc.lower() or "specific terms" in desc.lower()
        # Must also reference get_skill
        assert "get_skill" in desc

    def test_list_categories_has_use_case(self, tools):
        desc = _desc(tools, "list_categories")
        # Must not be a bare "list categories" — should say why
        assert "discover" in desc.lower() or "browse" in desc.lower()

    def test_all_descriptions_are_nonempty(self, tools):
        for tool in tools:
            assert tool.description and len(tool.description) > 20, (
                f"Tool '{tool.name}' has a too-short or empty description"
            )
