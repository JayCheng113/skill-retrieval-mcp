"""Tests for registering the server with third-party agent runtimes.

The risk here is not a wrong dict shape, it is damage to a file we do not own:
OpenClaw's config is JSON5 with user comments and Hermes' is hand-written YAML,
so both are delegated to the agent's own `mcp add`. These tests pin that
delegation, because a future "simplification" that parses those files directly
would pass any shape-based test while silently eating the user's comments.
"""

from __future__ import annotations

import json
import subprocess

import pytest

from skill_mcp import cli


@pytest.fixture
def openclaw_config(tmp_path):
    """A JSON5 config with comments — what an OpenClaw user actually has."""
    config = tmp_path / "openclaw.json"
    config.write_text(
        "{\n  // my own notes, do not lose these\n  mcp: { servers: {} },\n}\n",
        encoding="utf-8",
    )
    return config


def _stub_cli(monkeypatch, returncode=0, side_effect=None):
    """Pretend the agent binary exists and the user said yes; record the argv."""
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        if side_effect is not None:
            side_effect()
        return subprocess.CompletedProcess(argv, returncode)

    monkeypatch.setattr(cli.shutil, "which", lambda b: f"/usr/bin/{b}")
    monkeypatch.setattr(cli.click, "confirm", lambda *a, **k: True)
    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    return calls


def test_absent_binary_is_skipped_not_crashed(monkeypatch):
    monkeypatch.setattr(cli.shutil, "which", lambda _: None)
    monkeypatch.setattr(
        cli.subprocess, "run", lambda *a, **k: pytest.fail("must not run a missing binary")
    )

    assert cli._register_via_cli("openclaw", ["mcp", "add", "x"], "OpenClaw") is False


def test_openclaw_config_is_delegated_never_rewritten(openclaw_config, monkeypatch):
    """We hand OpenClaw its own arguments; we never touch its file."""
    before = openclaw_config.read_text(encoding="utf-8")
    calls = _stub_cli(monkeypatch)

    cli._register_openclaw({"command": "skill-mcp", "args": ["serve", "--transport", "stdio"]})

    assert openclaw_config.read_text(encoding="utf-8") == before
    assert "// my own notes, do not lose these" in before
    (argv,) = calls
    assert argv[1:3] == ["mcp", "add"]
    # --arg is a repeated flag in OpenClaw's parser, not a space-separated list,
    # so every server argument must carry its own.
    assert argv[-6:] == ["--arg", "serve", "--arg", "--transport", "--arg", "stdio"]


def test_declining_the_prompt_runs_nothing(monkeypatch):
    monkeypatch.setattr(cli.shutil, "which", lambda b: f"/usr/bin/{b}")
    monkeypatch.setattr(cli.click, "confirm", lambda *a, **k: False)
    monkeypatch.setattr(
        cli.subprocess, "run", lambda *a, **k: pytest.fail("must not run after a declined prompt")
    )

    assert cli._register_via_cli("hermes", ["mcp", "add", "x"], "Hermes") is False


def test_hermes_exit_zero_without_a_write_is_not_reported_as_registered(
    tmp_path, monkeypatch, capsys
):
    """`hermes mcp add` prints 'Cancelled.' and exits 0 when its prompt is not
    answered, so the exit code alone would let us claim a registration that
    never happened."""
    home = tmp_path / "hermes"
    home.mkdir()
    (home / "config.yaml").write_text("mcp_servers: {}\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(home))
    _stub_cli(monkeypatch)

    cli._register_hermes({"command": "skill-mcp", "args": ["serve"]})

    out = capsys.readouterr().out
    assert "not registered" in out
    assert "Registered in" not in out


def test_hermes_reports_registered_only_when_the_key_landed(tmp_path, monkeypatch, capsys):
    home = tmp_path / "hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))

    def land_the_key():
        (home / "config.yaml").write_text(
            "mcp_servers:\n  skill-retrieval:\n    command: skill-mcp\n    args: [serve]\n",
            encoding="utf-8",
        )

    calls = _stub_cli(monkeypatch, side_effect=land_the_key)

    cli._register_hermes({"command": "skill-mcp", "args": ["serve", "--transport", "stdio"]})

    out = capsys.readouterr().out
    assert "Registered in" in out
    assert "not registered" not in out
    # Upstream declares --args as argparse.REMAINDER, which swallows everything
    # after it, so every server argument has to trail it and no flag may follow.
    (argv,) = calls
    assert argv[argv.index("--args") :] == ["--args", "serve", "--transport", "stdio"]


def test_deepseek_prints_a_snippet_and_edits_nothing(tmp_path, monkeypatch, capsys):
    """DeepSeek Harness has no `mcp add`, and its overlay format is a developer
    preview whose examples carry executable !!js tags."""
    dsh = tmp_path / "dsh"
    dsh.mkdir()
    monkeypatch.setenv("DSH_HOME", str(dsh))

    cli._print_dsh_snippet({"command": "skill-mcp", "args": ["serve"]})

    out = capsys.readouterr().out
    assert "cordis.patch.yml" in out
    assert "@deepseek-ai/dsh-mcp-client" in out
    assert list(dsh.iterdir()) == []


def test_deepseek_snippet_is_silent_when_not_installed(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DSH_HOME", str(tmp_path / "absent"))
    cli._print_dsh_snippet({"command": "skill-mcp", "args": ["serve"]})
    assert capsys.readouterr().out == ""


def test_json_registration_survives_a_non_ascii_path(tmp_path):
    """MCP config files are UTF-8; reading them at the locale encoding corrupts
    or crashes on any non-ASCII path, which is routine outside en_US.

    The existing entry is written with ensure_ascii=False on purpose: escaped
    \\uXXXX would put pure ASCII on disk, which decodes identically under every
    candidate encoding and so could not detect the bug.
    """
    config = tmp_path / "mcp.json"
    config.write_text(
        json.dumps(
            {"mcpServers": {"existing": {"command": "C:/用户/项目/bin/x"}}}, ensure_ascii=False
        ),
        encoding="utf-8",
    )
    assert not config.read_bytes().isascii()

    cli._register_mcp_json(config, "skill-retrieval", {"command": "skill-mcp", "args": ["serve"]})

    data = json.loads(config.read_text(encoding="utf-8"))
    assert data["mcpServers"]["existing"]["command"] == "C:/用户/项目/bin/x"
    assert data["mcpServers"]["skill-retrieval"]["args"] == ["serve"]
