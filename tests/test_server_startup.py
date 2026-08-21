"""Startup must not block on the embedding model.

Importing sentence-transformers and validating the HuggingFace cache cost ~14s
on a cold start. Doing that during ``run_server`` stalled the MCP handshake for
that whole time, and a client cannot tell a slow handshake from a dead server.
"""

import threading
import time

import pytest

from skill_mcp import server


@pytest.fixture(autouse=True)
def reset_module_state():
    server._embedding = None
    server._embedding_spec = None
    yield
    server._embedding = None
    server._embedding_spec = None


def test_no_model_is_built_until_something_searches(monkeypatch):
    built = []

    class SlowModel:
        def __init__(self, model_name, backend):
            built.append((backend, model_name))

    monkeypatch.setattr(server, "EmbeddingModel", SlowModel)
    server._embedding_spec = ("sentence-transformers", "all-MiniLM-L6-v2")

    assert built == [], "recording the spec must not construct the model"

    server._get_embedding()
    assert built == [("sentence-transformers", "all-MiniLM-L6-v2")]


def test_concurrent_searches_share_one_model(monkeypatch):
    """A burst of tool calls during warm-up must not each load their own copy."""
    built = []

    class SlowModel:
        def __init__(self, model_name, backend):
            time.sleep(0.05)
            built.append(backend)

    monkeypatch.setattr(server, "EmbeddingModel", SlowModel)
    server._embedding_spec = ("sentence-transformers", "all-MiniLM-L6-v2")

    threads = [threading.Thread(target=server._get_embedding) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(built) == 1


def test_search_reports_unavailable_when_there_is_no_index():
    """Without an index there is no spec, so search must fail loudly, not hang."""
    assert server._get_embedding() is None
