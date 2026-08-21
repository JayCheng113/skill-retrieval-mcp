"""A first-time user has no cached model, so the local-first load must fall back.

Loading a cached model without contacting HuggingFace saves ~5s of round trips
on every start, but the same call raises when nothing is cached yet. If that
path ever stops falling back, the tool breaks for everyone installing it for the
first time -- which is exactly the population least able to diagnose it.
"""

import sys
import types

import pytest

from skill_mcp.embeddings import EmbeddingModel


class FakeModel:
    def get_sentence_embedding_dimension(self):
        return 384


@pytest.fixture
def fake_sentence_transformers(monkeypatch):
    calls = []

    def factory(should_fail_offline):
        def SentenceTransformer(model_name, **kwargs):
            calls.append(kwargs.get("local_files_only", False))
            if should_fail_offline and kwargs.get("local_files_only"):
                raise OSError(f"{model_name} is not cached and offline mode is on")
            return FakeModel()

        module = types.ModuleType("sentence_transformers")
        module.SentenceTransformer = SentenceTransformer
        monkeypatch.setitem(sys.modules, "sentence_transformers", module)
        return calls

    return factory


def test_uncached_model_still_loads(fake_sentence_transformers):
    calls = fake_sentence_transformers(should_fail_offline=True)

    model = EmbeddingModel(model_name="all-MiniLM-L6-v2")

    assert model.dimension == 384
    assert calls == [True, False], "must retry with downloads allowed"


def test_cached_model_never_reaches_the_network(fake_sentence_transformers):
    calls = fake_sentence_transformers(should_fail_offline=False)

    EmbeddingModel(model_name="all-MiniLM-L6-v2")

    assert calls == [True], "a cached model must not trigger a second, online load"
