"""Simple vector retrieval for skills."""

from __future__ import annotations

from skill_mcp.embeddings import EmbeddingModel
from skill_mcp.index import SkillIndex
from skill_mcp.schema import RetrievedSkill
from skill_mcp.store import SkillStore


def retrieve(
    query: str,
    store: SkillStore,
    index: SkillIndex,
    embedding_model: EmbeddingModel,
    k: int = 5,
) -> list[RetrievedSkill]:
    """Retrieve top-k skills by cosine similarity.

    Encodes the query, searches the FAISS index, and fetches full skill
    records from the store.
    """
    query_vec = embedding_model.encode_single(query)
    results = index.search(query_vec, k=k)

    retrieved = []
    for skill_id, score in results:
        skill = store.get_skill(skill_id)
        if skill:
            retrieved.append(
                RetrievedSkill(
                    skill=skill,
                    score=float(score),
                    retrieval_metadata={"method": "vector", "model": embedding_model.model_name},
                )
            )
    return retrieved
