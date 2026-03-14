"""FAISS-based vector index for skill retrieval."""

from __future__ import annotations

import json
from pathlib import Path

import faiss
import numpy as np

from skill_mcp.store import SkillStore
from skill_mcp.embeddings import EmbeddingModel


class SkillIndex:
    """FAISS-based vector index for skills."""

    def __init__(self, dimension: int) -> None:
        self.index = faiss.IndexFlatIP(dimension)
        self.skill_ids: list[str] = []
        self._dimension = dimension

    def build(
        self,
        store: SkillStore,
        embedding_model: EmbeddingModel,
        batch_size: int = 64,
    ) -> None:
        """Build index from all skills in store."""
        skills = store.get_all()
        if not skills:
            return

        texts = [s.to_embedding_text() for s in skills]
        ids = [s.id for s in skills]

        vectors = embedding_model.encode(texts, batch_size=batch_size)
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms = np.maximum(norms, 1e-10)
        vectors = vectors / norms

        self.index.add(vectors.astype(np.float32))
        self.skill_ids = ids

    def search(
        self, query_vector: np.ndarray, k: int = 5
    ) -> list[tuple[str, float]]:
        """Search for top-k similar skills. Returns list of (skill_id, score)."""
        qv = query_vector.astype(np.float32).reshape(1, -1)
        norm = np.linalg.norm(qv)
        if norm > 0:
            qv = qv / norm

        actual_k = min(k, self.index.ntotal)
        if actual_k == 0:
            return []

        scores, indices = self.index.search(qv, actual_k)
        results: list[tuple[str, float]] = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0:
                continue
            results.append((self.skill_ids[idx], float(score)))
        return results

    def save(self, path: Path) -> None:
        """Save index and skill IDs to disk."""
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self.index, str(path / "index.faiss"))
        with open(path / "skill_ids.json", "w") as f:
            json.dump(
                {"skill_ids": self.skill_ids, "dimension": self._dimension}, f
            )

    @classmethod
    def load(cls, path: Path) -> SkillIndex:
        """Load index and skill IDs from disk."""
        path = Path(path)
        with open(path / "skill_ids.json") as f:
            meta = json.load(f)
        idx = cls(dimension=meta["dimension"])
        idx.index = faiss.read_index(str(path / "index.faiss"))
        idx.skill_ids = meta["skill_ids"]
        return idx
