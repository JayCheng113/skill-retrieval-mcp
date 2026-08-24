"""Startup must not block on the embedding model.

Importing sentence-transformers and validating the HuggingFace cache cost ~14s
on a cold start. Doing that during ``run_server`` stalled the MCP handshake for
that whole time, and a client cannot tell a slow handshake from a dead server.
"""

import asyncio
import threading
import time

import pytest

from skill_mcp import server


@pytest.fixture(autouse=True)
def reset_module_state():
    """The server keeps its store, index and model in module globals.

    ``run_server`` assigns them on the paths that find something and leaves them
    alone otherwise, which is harmless for a process that serves once but lets
    one test here observe another's index.
    """
    saved = (server._store, server._index)
    server._embedding = None
    server._embedding_spec = None
    server._store = None
    server._index = None
    yield
    server._embedding = None
    server._embedding_spec = None
    server._store, server._index = saved


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


def test_startup_survives_the_state_init_leaves_behind(tmp_path, monkeypatch):
    """`skill-mcp init` offers registration before anything has been imported,
    so at that moment there is no index and an empty database.

    That ordering is only safe because startup degrades instead of failing.
    OpenClaw's `mcp add` connects to the server and discards the entry unless
    the handshake succeeds, so a startup that raised on a missing index would
    not produce a broken registration — it would produce no registration, with
    the user's only clue being an exit code from someone else's binary.
    """
    from skill_mcp.config import Config

    reached_transport = []

    async def fake_stdio():
        reached_transport.append(True)

    monkeypatch.setattr(server.server, "run_stdio_async", fake_stdio)

    data_dir = tmp_path / "fresh"
    data_dir.mkdir()
    asyncio.run(server.run_server(Config(data_dir=str(data_dir))))

    assert reached_transport, "startup did not reach the transport"
    assert server._index is None
    assert server._store.count() == 0
