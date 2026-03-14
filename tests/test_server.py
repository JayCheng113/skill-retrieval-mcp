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
