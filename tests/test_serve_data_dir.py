"""serve must honour --data-dir, or the MCP server silently serves nothing."""

import sqlite3

import pytest
from click.testing import CliRunner

from skill_mcp.cli import main


@pytest.fixture
def runner():
    return CliRunner()


def _seed_db(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE skills (id TEXT PRIMARY KEY)")
    conn.commit()
    conn.close()


def test_serve_reads_the_data_dir_it_was_given(runner, tmp_path, monkeypatch):
    """A data dir with no config.yaml is the normal case after `pull --data-dir`.

    The server has no way to report "you pointed me somewhere empty" — a missing
    database silently degrades to an in-memory store, so the agent is told the
    knowledge base has zero skills rather than that it was misconfigured.
    """
    data_dir = tmp_path / "custom"
    _seed_db(data_dir / "skills.db")
    assert not (data_dir / "config.yaml").exists()

    seen = {}

    async def fake_run_server(config, transport="stdio"):
        seen["db_path"] = config.db_path
        seen["index_dir"] = config.index_dir

    monkeypatch.setattr("skill_mcp.server.run_server", fake_run_server)
    result = runner.invoke(main, ["--data-dir", str(data_dir), "serve"])

    assert result.exit_code == 0, result.output
    assert seen["db_path"] == data_dir / "skills.db"
    assert seen["index_dir"] == data_dir / "index"


def test_serve_honours_the_data_dir_env_var(runner, tmp_path, monkeypatch):
    """Agent configs set env vars far more often than they pass flags."""
    data_dir = tmp_path / "from-env"
    _seed_db(data_dir / "skills.db")

    seen = {}

    async def fake_run_server(config, transport="stdio"):
        seen["db_path"] = config.db_path

    monkeypatch.setattr("skill_mcp.server.run_server", fake_run_server)
    monkeypatch.setenv("SKILL_MCP_DATA_DIR", str(data_dir))
    result = runner.invoke(main, ["serve"])

    assert result.exit_code == 0, result.output
    assert seen["db_path"] == data_dir / "skills.db"
