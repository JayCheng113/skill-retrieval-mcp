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
        self.embedding_info: dict[str, str] = {}

    def build(
        self,
        store: SkillStore,
        embedding_model: EmbeddingModel,
        batch_size: int = 64,
        show_progress: bool = True,
    ) -> None:
        """Build index from all skills in store (full rebuild)."""
        skills = store.get_all()
        if not skills:
            return
        texts = [s.to_embedding_text() for s in skills]
        ids = [s.id for s in skills]
        vectors = self._encode_batch(texts, embedding_model, batch_size, show_progress)
        self.index.add(vectors)
        self.skill_ids = ids

    def update(
        self,
        store: SkillStore,
        embedding_model: EmbeddingModel,
        batch_size: int = 64,
        show_progress: bool = True,
    ) -> int:
        """Incrementally add new skills to existing index.

        Returns the number of new skills added, or -1 if a full rebuild
        is required (e.g. skills were deleted from the store).
        """
        store_ids = store.all_ids()
        indexed_ids = set(self.skill_ids)

        # Detect deletions — FAISS doesn't support removal, need full rebuild
        if not indexed_ids.issubset(store_ids):
            return -1

        new_ids = store_ids - indexed_ids
        if not new_ids:
            return 0

        new_skills = [store.get_skill(sid) for sid in new_ids]
        new_skills = [s for s in new_skills if s is not None]
        if not new_skills:
            return 0

        texts = [s.to_embedding_text() for s in new_skills]
        vectors = self._encode_batch(texts, embedding_model, batch_size, show_progress)
        self.index.add(vectors)
        self.skill_ids.extend([s.id for s in new_skills])
        return len(new_skills)

    def _encode_batch(
        self,
        texts: list[str],
        embedding_model: EmbeddingModel,
        batch_size: int,
        show_progress: bool,
    ) -> np.ndarray:
        """Encode texts, normalize, return float32 array ready for FAISS."""
        from tqdm import tqdm

        all_vectors = []
        iterator = range(0, len(texts), batch_size)
        if show_progress and len(texts) > batch_size:
            iterator = tqdm(iterator, desc="Encoding skills", unit="batch")
        for i in iterator:
            batch = texts[i : i + batch_size]
            batch_vecs = embedding_model.encode(batch, batch_size=batch_size)
            all_vectors.append(batch_vecs)

        vectors = np.vstack(all_vectors)
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms = np.maximum(norms, 1e-10)
        return (vectors / norms).astype(np.float32)

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
        meta = {"skill_ids": self.skill_ids, "dimension": self._dimension}
        if self.embedding_info:
            meta["embedding"] = self.embedding_info
        with open(path / "skill_ids.json", "w") as f:
            json.dump(meta, f)

    @classmethod
    def load(cls, path: Path) -> SkillIndex:
        """Load index and skill IDs from disk."""
        path = Path(path)
        with open(path / "skill_ids.json") as f:
            meta = json.load(f)
        idx = cls(dimension=meta["dimension"])
        idx.index = faiss.read_index(str(path / "index.faiss"))
        idx.skill_ids = meta["skill_ids"]
        idx.embedding_info = meta.get("embedding", {})
        return idx
