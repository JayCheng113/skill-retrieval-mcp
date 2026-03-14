"""Embedding model wrapper supporting multiple backends."""

from __future__ import annotations

import hashlib

import numpy as np


class EmbeddingModel:
    """Wraps different embedding backends."""

    def __init__(
        self,
        model_name: str = "text-embedding-3-large",
        backend: str = "openai",
    ) -> None:
        self.model_name = model_name
        self.backend = backend
        self._dimension: int | None = None

        if backend == "openai":
            import openai
            self._client = openai.OpenAI()
        elif backend == "sentence-transformers":
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(model_name)
            self._dimension = self._model.get_sentence_embedding_dimension()
        elif backend == "ollama":
            self._ollama_url = "http://localhost:11434/api/embeddings"
        elif backend == "mock":
            self._dimension = 128
        else:
            raise ValueError(f"Unsupported backend: {backend}")

    def encode(self, texts: list[str], batch_size: int = 32) -> np.ndarray:
        """Encode texts to vectors. Returns (N, dim) array."""
        if self.backend == "mock":
            return np.array([self._mock_encode(t) for t in texts], dtype=np.float32)

        if self.backend == "openai":
            all_embeddings: list[np.ndarray] = []
            for i in range(0, len(texts), batch_size):
                batch = texts[i : i + batch_size]
                response = self._client.embeddings.create(
                    input=batch,
                    model=self.model_name,
                )
                for item in response.data:
                    all_embeddings.append(np.array(item.embedding, dtype=np.float32))
                if self._dimension is None and response.data:
                    self._dimension = len(response.data[0].embedding)
            return np.array(all_embeddings, dtype=np.float32)

        if self.backend == "sentence-transformers":
            embeddings = self._model.encode(
                texts, batch_size=batch_size, show_progress_bar=False
            )
            return np.array(embeddings, dtype=np.float32)

        if self.backend == "ollama":
            all_embeddings: list[np.ndarray] = []
            import httpx
            for text in texts:
                resp = httpx.post(
                    self._ollama_url,
                    json={"model": self.model_name, "prompt": text},
                    timeout=30.0,
                )
                resp.raise_for_status()
                embedding = resp.json()["embedding"]
                all_embeddings.append(np.array(embedding, dtype=np.float32))
                if self._dimension is None:
                    self._dimension = len(embedding)
            return np.array(all_embeddings, dtype=np.float32)

        raise ValueError(f"Unsupported backend: {self.backend}")

    def encode_single(self, text: str) -> np.ndarray:
        """Encode a single text."""
        return self.encode([text])[0]

    @property
    def dimension(self) -> int:
        """Return the embedding dimension."""
        if self._dimension is not None:
            return self._dimension
        if self.backend == "openai":
            vec = self.encode_single("hello")
            self._dimension = len(vec)
            return self._dimension
        if self.backend == "ollama":
            vec = self.encode_single("hello")
            self._dimension = len(vec)
            return self._dimension
        raise RuntimeError("Dimension not available")

    def _mock_encode(self, text: str) -> np.ndarray:
        """Deterministic hash-based mock embedding."""
        h = hashlib.sha256(text.encode()).digest()
        seed = int.from_bytes(h[:4], "little")
        rng = np.random.RandomState(seed)
        vec = rng.randn(128).astype(np.float32)
        vec = vec / np.linalg.norm(vec)
        return vec
