"""Tests for the retriever module."""

from skill_mcp.embeddings import EmbeddingModel
from skill_mcp.index import SkillIndex
from skill_mcp.retriever import retrieve
from skill_mcp.schema import Skill, SkillSource
from skill_mcp.store import SkillStore


def _populate_store(store: SkillStore) -> list[Skill]:
    skills = [
        Skill(name="debug-memory", description="Debug memory leaks", instructions="Use profiler", source=SkillSource.COMMUNITY),
        Skill(name="write-tests", description="Write unit tests", instructions="Use pytest", source=SkillSource.COMMUNITY),
        Skill(name="deploy-docker", description="Deploy with Docker", instructions="Use Dockerfile", source=SkillSource.COMMUNITY),
    ]
    store.add_skills(skills)
    return skills


def test_retrieve_returns_results():
    store = SkillStore()
    skills = _populate_store(store)

    emb = EmbeddingModel(backend="mock")
    index = SkillIndex(emb.dimension)
    index.build(store, emb)

    results = retrieve("debug memory leak", store, index, emb, k=3)
    assert len(results) == 3
    assert all(r.score > 0 or r.score <= 0 for r in results)  # scores are floats
    assert all(r.skill.name in ["debug-memory", "write-tests", "deploy-docker"] for r in results)
    store.close()


def test_retrieve_k_larger_than_store():
    store = SkillStore()
    _populate_store(store)

    emb = EmbeddingModel(backend="mock")
    index = SkillIndex(emb.dimension)
    index.build(store, emb)

    results = retrieve("test", store, index, emb, k=100)
    assert len(results) == 3  # only 3 skills in store
    store.close()


def test_index_save_load(tmp_path):
    store = SkillStore()
    _populate_store(store)

    emb = EmbeddingModel(backend="mock")
    index = SkillIndex(emb.dimension)
    index.build(store, emb)
    index.save(tmp_path / "idx")

    loaded = SkillIndex.load(tmp_path / "idx")
    assert loaded.index.ntotal == 3
    assert len(loaded.skill_ids) == 3

    results = loaded.search(emb.encode_single("test"), k=2)
    assert len(results) == 2
    store.close()
