"""Every command this CLI tells a user or an agent to run next.

A printed command is as much a product surface as a config file we write: it is
pasted verbatim, and `--data-dir` is the one thing that cannot be recovered once
it is dropped, because the config recording that choice lives inside the chosen
directory. A command that drops it succeeds against the *default* directory and
reports nothing wrong — the store it was meant to touch is simply not the one it
touched.

These tests scan whatever a command actually printed rather than naming the
strings, so a message added later is covered without being listed here.
"""

from __future__ import annotations

import json
import os
import re
import shlex
from pathlib import Path

import pytest
from click.testing import CliRunner

from skill_mcp.cli import main
from skill_mcp.schema import Skill, SkillSource
from skill_mcp.store import SkillStore

# `skill-mcp ...` up to a backtick or end of line.
#
# A token is one or more adjacent quoted or bare runs with no space between them,
# not a single quoted run: `shlex.quote` renders an apostrophe by *closing* the
# quote, escaping it and reopening (`'O'"'"'Brien'`), so a token alternation that
# stops at the first closing quote truncates a correctly quoted path and then
# reports it as unscoped.
_ATOM = r"\"[^\"]*\"|'[^']*'|[^\s`'\"]+"
_COMMAND = re.compile(rf"skill-mcp(?: (?:{_ATOM})+)+")


def _printed_commands(output: str) -> list[str]:
    return [m.group(0).rstrip(".") for m in _COMMAND.finditer(output)]


def _split(line: str) -> list[str]:
    if os.name == "nt":
        from tests.test_registration import _windows_argv

        return _windows_argv(line)
    return shlex.split(line)


def assert_every_command_is_scoped(output: str, data_dir: Path) -> None:
    commands = _printed_commands(output)
    assert commands, f"no command found in output: {output!r}"
    for line in commands:
        argv = _split(line)
        assert "--data-dir" in argv, (line, output)
        value = argv[argv.index("--data-dir") + 1]
        assert Path(value) == data_dir.resolve(), (line, output)


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def skills_dir(tmp_path):
    base = tmp_path / "skills"
    for name in ("alpha", "beta"):
        d = base / name
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(
            f'---\nname: "{name}"\ndescription: "does {name}"\n---\n\n## Instructions\n\n{name}\n'
        )
    return base


@pytest.fixture(params=["elsewhere", "my data", "O'Brien"])
def data_dir(request, tmp_path, monkeypatch):
    """A non-default data directory, with the default pointed somewhere empty.

    The default has to move too: a command that drops `--data-dir` would
    otherwise write into the developer's real `~/.skill-mcp`.

    Parametrised over names that need quoting, because that is where a command
    stops surviving the round trip: a space ends the argument and an apostrophe
    is escaped by closing and reopening the quote. Both are ordinary in a Windows
    user profile path.
    """
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return tmp_path / request.param


def _init(runner, data_dir):
    result = runner.invoke(main, ["--data-dir", str(data_dir), "init", "--no-register"])
    assert result.exit_code == 0, result.output
    return result


def _import(runner, data_dir, skills_dir, *extra):
    return runner.invoke(
        main,
        [
            "--data-dir",
            str(data_dir),
            "import",
            "--source",
            "directory",
            "--path",
            str(skills_dir),
            *extra,
        ],
    )


def test_init_next_steps_are_scoped(runner, data_dir):
    assert_every_command_is_scoped(_init(runner, data_dir).output, data_dir)


def test_import_without_an_index_is_scoped(runner, data_dir, skills_dir):
    _init(runner, data_dir)
    result = _import(runner, data_dir, skills_dir)
    assert "No index found" in result.output, result.output
    assert_every_command_is_scoped(result.output, data_dir)


def test_import_that_skips_the_index_is_scoped(runner, data_dir, skills_dir):
    _init(runner, data_dir)
    _import(runner, data_dir, skills_dir, "--no-index")
    assert (
        runner.invoke(
            main, ["--data-dir", str(data_dir), "build-index", "--backend", "mock"]
        ).exit_code
        == 0
    )
    (skills_dir / "gamma").mkdir()
    (skills_dir / "gamma" / "SKILL.md").write_text(
        '---\nname: "gamma"\ndescription: "does gamma"\n---\n\n## Instructions\n\ngamma\n'
    )

    result = _import(runner, data_dir, skills_dir, "--no-index")

    assert "--no-index" in result.output, result.output
    assert_every_command_is_scoped(result.output, data_dir)


def test_search_without_a_database_is_scoped(runner, data_dir):
    data_dir.mkdir()
    result = runner.invoke(main, ["--data-dir", str(data_dir), "search", "anything"])
    assert_every_command_is_scoped(result.output, data_dir)


def test_search_without_an_index_is_scoped(runner, data_dir, skills_dir):
    _init(runner, data_dir)
    _import(runner, data_dir, skills_dir, "--no-index")
    result = runner.invoke(main, ["--data-dir", str(data_dir), "search", "alpha"])
    assert_every_command_is_scoped(result.output, data_dir)


def test_status_without_a_database_is_scoped(runner, data_dir):
    data_dir.mkdir()
    result = runner.invoke(main, ["--data-dir", str(data_dir), "status"])
    assert_every_command_is_scoped(result.output, data_dir)


def test_status_warning_about_a_stale_index_is_scoped(runner, data_dir, skills_dir):
    _init(runner, data_dir)
    _import(runner, data_dir, skills_dir, "--no-index")
    runner.invoke(main, ["--data-dir", str(data_dir), "build-index", "--backend", "mock"])
    store = SkillStore(data_dir / "skills.db")
    store.add_skill(
        Skill(
            name="late", description="added later", instructions="x", source=SkillSource.COMMUNITY
        )
    )
    store.close()

    result = runner.invoke(main, ["--data-dir", str(data_dir), "status"])

    assert "WARNING" in result.output, result.output
    assert_every_command_is_scoped(result.output, data_dir)


def test_build_index_refusing_a_model_change_is_scoped(runner, data_dir, skills_dir):
    _init(runner, data_dir)
    _import(runner, data_dir, skills_dir, "--no-index")
    runner.invoke(main, ["--data-dir", str(data_dir), "build-index", "--backend", "mock"])

    result = runner.invoke(
        main, ["--data-dir", str(data_dir), "build-index", "--backend", "mock", "--model", "other"]
    )

    assert "--force" in result.output, result.output
    assert_every_command_is_scoped(result.output, data_dir)


def test_import_refusing_a_model_change_is_scoped(runner, data_dir, skills_dir):
    """`_auto_index` refuses when the index was built with a different model."""
    _init(runner, data_dir)
    _import(runner, data_dir, skills_dir, "--no-index")
    runner.invoke(main, ["--data-dir", str(data_dir), "build-index", "--backend", "mock"])
    from skill_mcp.config import load_config, save_config

    config = load_config(data_dir / "config.yaml")
    config.embedding.model = "something-else"
    save_config(config)
    (skills_dir / "gamma").mkdir()
    (skills_dir / "gamma" / "SKILL.md").write_text(
        '---\nname: "gamma"\ndescription: "does gamma"\n---\n\n## Instructions\n\ngamma\n'
    )

    result = _import(runner, data_dir, skills_dir)

    assert "Skipping auto-index" in result.output, result.output
    assert_every_command_is_scoped(result.output, data_dir)


def test_pull_next_step_is_scoped(runner, data_dir, tmp_path, monkeypatch):
    import skill_mcp.hub as hub

    seed = tmp_path / "seed.db"
    store = SkillStore(seed)
    store.add_skill(
        Skill(name="a", description="d", instructions="i", source=SkillSource.COMMUNITY)
    )
    store.close()
    monkeypatch.setattr(hub, "download_skills_db", lambda: seed)

    result = runner.invoke(main, ["--data-dir", str(data_dir), "pull"])

    assert result.exit_code == 0, result.output
    assert_every_command_is_scoped(result.output, data_dir)


def test_the_server_tells_the_agent_which_directory_to_repair(tmp_path, monkeypatch):
    """The server is started by an agent with `--data-dir`, and answers with a
    command the user is expected to run in a shell. Dropping the directory there
    sends them to repair one that was never broken.
    """
    from skill_mcp import server
    from skill_mcp.config import Config

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    data_dir = tmp_path / "elsewhere"
    data_dir.mkdir()

    monkeypatch.setattr(server, "_store", None)
    monkeypatch.setattr(server, "_index", None)
    monkeypatch.setattr(server, "_embedding", None)
    monkeypatch.setattr(server, "_embedding_spec", None)
    server.configure_hints(Config(data_dir=str(data_dir)))

    payload = json.loads(server._handle_search_skills({"query": "x", "k": 1})[0].text)

    assert_every_command_is_scoped(payload["error"], data_dir)
