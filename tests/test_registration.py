"""Tests for registering the server with third-party agent runtimes.

The risk here is not a wrong dict shape, it is damage to a file we do not own:
OpenClaw's config is JSON5 with user comments and Hermes' is hand-written YAML,
so both are delegated to the agent's own `mcp add`. These tests pin that
delegation, because a future "simplification" that parses those files directly
would pass any shape-based test while silently eating the user's comments.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from skill_mcp import cli
from skill_mcp import config as config_mod

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib


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


def test_hermes_saved_but_disabled_is_not_reported_as_registered(tmp_path, monkeypatch, capsys):
    """When Hermes cannot reach the server it offers to save the entry anyway,
    and what it writes is `enabled: false`. Its agent then filters disabled
    servers out, so the key being present says nothing about the tools being
    reachable — the one failure the user would otherwise never be told about."""
    home = tmp_path / "hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))

    def land_it_disabled():
        (home / "config.yaml").write_text(
            "mcp_servers:\n"
            "  skill-retrieval:\n"
            "    command: skill-mcp\n"
            "    args: [serve]\n"
            "    enabled: false\n",
            encoding="utf-8",
        )

    _stub_cli(monkeypatch, side_effect=land_it_disabled)

    cli._register_hermes({"command": "skill-mcp", "args": ["serve"]})

    out = capsys.readouterr().out
    assert "Registered in" not in out
    assert "disabled" in out
    # The user has to be able to act on it, which means knowing what to re-run.
    assert "hermes mcp test skill-retrieval" in out


@pytest.mark.parametrize(
    ("flag", "expected"),
    [
        # Copied from hermes_cli.tools_config._parse_enabled_flag, which is the
        # function that decides whether the agent ever sees this server.
        ("false", "disabled"),
        ("off", "disabled"),
        ("no", "disabled"),
        ("0", "disabled"),
        ("true", "enabled"),
        ("on", "enabled"),
        ("yes", "enabled"),
        ("  FALSE  ", "disabled"),
        # Everything it does not recognise means enabled, so reading these as
        # disabled would tell the user to repair a server that already works.
        ("maybe", "enabled"),
        ("", "enabled"),
        (None, "enabled"),
    ],
)
def test_enabled_is_read_the_way_hermes_reads_it(tmp_path, flag, expected):
    config = tmp_path / "config.yaml"
    value = "null" if flag is None else json.dumps(flag)
    config.write_text(
        f"mcp_servers:\n  skill-retrieval:\n    command: skill-mcp\n    enabled: {value}\n",
        encoding="utf-8",
    )

    assert cli._hermes_server_state(config, "skill-retrieval") == expected


@pytest.mark.parametrize(
    "config_text",
    [
        "mcp_servers: not-a-dict\n",
        "mcp_servers:\n  - skill-retrieval\n",
        "mcp_servers:\n  skill-retrieval: null\n",
        "just a string\n",
        "mcp_servers: {skill-retrieval: {command: skill-mcp}\n",  # unbalanced brace
    ],
)
def test_a_hand_broken_hermes_config_cannot_abort_init(tmp_path, monkeypatch, capsys, config_text):
    """This read-back exists because Hermes' config is hand-written, so it has
    to assume the file is shaped however a human left it.

    Registration is one step of `skill-mcp init`; raising here would take the
    whole command down over a file we only ever read.
    """
    home = tmp_path / "hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    (home / "config.yaml").write_text(config_text, encoding="utf-8")
    _stub_cli(monkeypatch)

    cli._register_hermes({"command": "skill-mcp", "args": ["serve"]})

    assert "Registered in" not in capsys.readouterr().out


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


def test_deepseek_snippet_adds_a_row_rather_than_patching_an_absent_one(
    tmp_path, monkeypatch, capsys
):
    """A cordis.patch.yml holds operations, not rows.

    An operation with an `id` and no `insert` means "override the row that
    already has this id", so pasting a bare row registers nothing: the id
    matches no entry, and DSH answers that with a warning on stderr rather than
    an error. The user would be told to do something that silently does not
    work, so the snippet is checked here by parsing it and asking which
    operation it is — the same question DSH's patch algorithm asks.
    """
    import yaml

    dsh = tmp_path / "dsh"
    dsh.mkdir()
    monkeypatch.setenv("DSH_HOME", str(dsh))

    cli._print_dsh_snippet({"command": "skill-mcp", "args": ["serve", "--transport", "stdio"]})

    snippet = capsys.readouterr().out.split("cordis.patch.yml", 1)[1].split("\n", 1)[1]
    ops = yaml.safe_load(snippet)
    assert isinstance(ops, list), "a patch file is a top-level list of operations"
    (op,) = ops
    assert "insert" in op, f"this is an id-targeted override, not an insert: {op}"

    (row,) = op["insert"]
    assert row["name"] == "@deepseek-ai/dsh-mcp-client"
    config = row["config"]
    assert config["transport"] == "stdio"
    assert config["command"] == "skill-mcp"
    assert config["args"] == ["serve", "--transport", "stdio"]
    # DSH builds tool names as mcp__<serverName>__<tool> and rejects anything
    # outside this shape, so a name it will not accept yields no tools at all.
    assert re.fullmatch(r"[A-Za-z0-9_-]{1,32}", config["serverName"])


def test_deepseek_snippet_is_silent_when_not_installed(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DSH_HOME", str(tmp_path / "absent"))
    cli._print_dsh_snippet({"command": "skill-mcp", "args": ["serve"]})
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize(
    ("label", "text"),
    [
        ("empty file", ""),
        # Cursor and VS Code both accept comments in theirs, so this is a config
        # that works for its owner and that we still must not re-serialise.
        ("comments", '{\n  // my notes, do not lose these\n  "mcpServers": {}\n}\n'),
        ("trailing comma", '{"mcpServers": {"a": {"command": "x"},}}'),
        ("root is a list", "[]"),
        ("mcpServers is a list", '{"mcpServers": []}'),
    ],
)
def test_an_unexpected_json_config_is_left_alone_rather_than_guessed_at(
    tmp_path, capsys, label, text
):
    """This is the path Claude Code, Gemini CLI and Cursor all share, so it sees
    whatever three different tools and their users have left on disk.

    A file we cannot parse is far more likely to be one we would damage than one
    that is broken, and rewriting it is exactly the harm that sends OpenClaw and
    Hermes through their own `mcp add`. Registration is also one step of
    `skill-mcp init`, so raising here would take down the steps after it.
    """
    config = tmp_path / "mcp.json"
    config.write_bytes(text.encode("utf-8"))
    before = config.read_bytes()

    cli._register_mcp_json(config, "skill-retrieval", {"command": "skill-mcp", "args": ["serve"]})

    assert config.read_bytes() == before, f"{label}: rewrote a config it could not understand"
    out = capsys.readouterr().out
    assert "Registered in" not in out
    # Refusing is only acceptable if the user can still finish the job by hand.
    assert "skill-retrieval" in out


@pytest.mark.parametrize(
    "config_text",
    [
        # The first three are valid TOML that Codex loads today.
        'mcp_servers = "disabled"\nmodel = "gpt-5"\n',
        'mcp_servers = []\nmodel = "gpt-5"\n',
        # An inline table parses to a dict exactly like a standard table does,
        # but it is closed: no `[mcp_servers.x]` header may extend it. Nothing
        # in the parsed value distinguishes the two, which is why the append is
        # checked by parsing the result instead of by inspecting the shape.
        'mcp_servers = { other = { command = "x" } }\nmodel = "gpt-5"\n',
        '[mcp_servers.other]\ncommand = "x"\n\n[bad\n',
    ],
)
def test_a_codex_config_we_cannot_extend_is_left_untouched(tmp_path, capsys, config_text):
    """Registration here appends a `[mcp_servers.<name>]` header, which is only
    valid TOML if nothing already claims that key in a form it cannot extend.

    When it collides Codex refuses to load the whole file — the user loses their
    entire setup over our one entry, and the parse error points at our table
    rather than at anything they wrote.
    """
    config = tmp_path / "config.toml"
    config.write_text(config_text, encoding="utf-8")

    cli._register_codex_toml(config, "skill-retrieval", {"command": "skill-mcp", "args": ["serve"]})

    assert config.read_text(encoding="utf-8") == config_text
    assert "Registered in" not in capsys.readouterr().out


def test_a_codex_config_that_is_not_utf8_cannot_abort_init(tmp_path, capsys):
    """TOML is defined as UTF-8, so a config saved at a Windows locale encoding
    is already broken for Codex too.

    Decoding it is the first thing this function does, though, and registration
    is one step of `skill-mcp init` — an uncaught UnicodeDecodeError here takes
    down the steps after it as well.
    """
    config = tmp_path / "config.toml"
    raw = 'model = "gpt-5"  # café\n'.encode("latin-1")
    config.write_bytes(raw)

    cli._register_codex_toml(config, "skill-retrieval", {"command": "skill-mcp", "args": ["serve"]})

    assert config.read_bytes() == raw
    assert "Registered in" not in capsys.readouterr().out


def test_codex_registration_without_a_toml_parser_cannot_abort_init(tmp_path, monkeypatch, capsys):
    """`tomllib` only joined the stdlib in 3.11, and this project supports 3.10.

    Registering with Codex is one step of `init`, so a parser that is not there
    has to end in the same printed snippet as a config we decline to touch. This
    hides the backport too, so it exercises the branch on every interpreter
    rather than only on the one where it is reachable by default.
    """
    for module in ("tomllib", "tomli"):
        monkeypatch.setitem(sys.modules, module, None)
    config = tmp_path / "config.toml"
    original = 'model = "gpt-5"\n'
    config.write_text(original, encoding="utf-8")

    cli._register_codex_toml(config, "skill-retrieval", {"command": "skill-mcp", "args": ["serve"]})

    assert config.read_text(encoding="utf-8") == original
    out = capsys.readouterr().out
    assert "Registered in" not in out
    # Refusing is only acceptable if the user can still finish the job by hand.
    assert "skill-retrieval" in out


def test_codex_registration_keeps_the_rest_of_the_config(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text('model = "gpt-5"\n\n[mcp_servers.other]\ncommand = "x"\n', encoding="utf-8")

    cli._register_codex_toml(config, "skill-retrieval", {"command": "skill-mcp", "args": ["serve"]})

    data = tomllib.loads(config.read_text(encoding="utf-8"))
    assert data["model"] == "gpt-5"
    assert data["mcp_servers"]["other"]["command"] == "x"
    assert data["mcp_servers"]["skill-retrieval"]["args"] == ["serve"]


def test_the_registered_command_is_one_the_agent_can_find(tmp_path, monkeypatch):
    """The agent spawns this command itself, and the PATH it was launched with is
    not the one that ran `init`.

    Editors and desktop apps start from a session that has never seen the user's
    venv or pipx shim, so a bare name there fails with an ENOENT on a name the
    user never typed and a server that simply never appears. Writing the
    resolved path can go stale if that install moves, but it says so.
    """
    monkeypatch.chdir(tmp_path)
    # Keep every `~` in the registration code pointed inside the tmp dir; this
    # function writes to real agent configs.
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("DSH_HOME", str(tmp_path / "absent"))
    installed = tmp_path / "venv" / "bin" / "skill-mcp"
    monkeypatch.setattr(cli.shutil, "which", lambda b: str(installed) if b == "skill-mcp" else None)
    monkeypatch.setattr(cli.click, "confirm", lambda *a, **k: True)

    cli._try_register_mcp(tmp_path)

    data = json.loads((tmp_path / ".mcp.json").read_text(encoding="utf-8"))
    assert data["mcpServers"]["skill-retrieval"]["command"] == str(installed)


def test_the_registered_server_looks_where_init_just_put_things(tmp_path, monkeypatch):
    """`init --data-dir` prepares one directory and the agent must start us on it.

    A server pointed at the wrong directory does not fail: it starts cleanly,
    the agent lists its tools, and every search comes back empty. `~` is
    re-resolved in whatever environment the agent spawns us from, and the
    config that records the choice is written inside the chosen directory, so
    nothing recovers it once the argv has dropped it.

    Asserted by running the registered argv and asking the CLI where it looks,
    rather than by reading back the argv we just wrote.
    """
    project = tmp_path / "project"
    project.mkdir()
    data_dir = tmp_path / "elsewhere"
    data_dir.mkdir()
    home = tmp_path / "home"
    monkeypatch.chdir(project)
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("DSH_HOME", str(tmp_path / "absent"))
    monkeypatch.setattr(cli.shutil, "which", lambda b: None)
    monkeypatch.setattr(cli.click, "confirm", lambda *a, **k: True)

    cli._try_register_mcp(data_dir)

    entry = json.loads((project / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"][
        "skill-retrieval"
    ]
    # `status` reports the directory `serve` would open; everything else is the
    # argv the agent was handed.
    argv = ["status" if a == "serve" else a for a in entry["args"]]
    result = subprocess.run(
        [sys.executable, "-m", "skill_mcp.cli", *argv],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "HOME": str(home),
            "USERPROFILE": str(home),
            "PYTHONPATH": os.pathsep.join(p for p in sys.path if p),
        },
    )
    assert result.returncode == 0, result.stderr
    assert str(data_dir) in result.stdout, result.stdout


def _windows_argv(line: str) -> list[str]:
    """The real Windows command-line parser, not a model of one."""
    import ctypes

    to_argv = ctypes.windll.shell32.CommandLineToArgvW
    to_argv.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_int)]
    to_argv.restype = ctypes.POINTER(ctypes.c_wchar_p)
    argc = ctypes.c_int(0)
    argv = to_argv(line, ctypes.byref(argc))
    try:
        return [argv[i] for i in range(argc.value)]
    finally:
        ctypes.windll.kernel32.LocalFree(argv)


def _shell_parsers() -> dict:
    """Every parser that can see a line `init` prints, on this platform.

    `CommandLineToArgvW` is what turns a Windows command line into argv, so on
    Windows it is the parser, not a model of one. `shlex` is POSIX word
    splitting, which is what sh and the bash shipped with Git for Windows do to
    a line before any word is expanded.

    Neither performs expansion, so neither can speak for a directory whose name
    contains `%`, `$` or a backtick — and no quoting can either, on Windows. See
    `scope_flag`; those names are out of scope rather than covered here.
    """
    if os.name == "nt":
        return {"CommandLineToArgvW": _windows_argv, "POSIX splitting (Git bash)": shlex.split}
    return {"sh": shlex.split}


@pytest.mark.parametrize("name", ["plain", "my data", "O'Brien", "a&b", 'a"b', "trailing\\"])
def test_the_next_steps_init_prints_target_the_directory_it_just_set_up(
    name, tmp_path, monkeypatch
):
    """The commands `init` tells the user to run next are part of the product.

    Two ways they mislead: printed with no data directory, a user who chose one
    and then pastes them populates the default directory instead — success
    everywhere, and a server that finds nothing. Printed with a directory the
    shell re-splits, the paste runs a different command than the one shown.

    Asserted by handing the line to the parsers that will actually see it,
    because a substring check passes on a line whose quoting is broken.
    """
    from click.testing import CliRunner

    if os.name == "nt" and set(name) & set('<>:"/\\|?*'):
        pytest.skip("not a legal Windows directory name")

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOME", str(home))
    data_dir = tmp_path / name

    result = CliRunner().invoke(
        cli.main, ["init", "--data-dir", str(data_dir), "--no-register"], catch_exceptions=False
    )

    printed = [
        ln.strip() for ln in result.output.splitlines() if ln.strip().startswith("skill-mcp")
    ]
    assert printed
    for line in printed:
        for shell, split in _shell_parsers().items():
            argv = split(line)
            assert argv[1] == "--data-dir", (shell, line, argv)
            assert Path(argv[2]) == data_dir.resolve(), (shell, line, argv)
            # The subcommand and its options follow the directory; a quote that
            # never closes swallows them into it without any error.
            assert argv[3:], (shell, line, argv)


@pytest.mark.skipif(
    os.name != "nt",
    reason="a directory that resolves with a trailing separator is a Windows drive root; "
    "the POSIX form of the same defect is the `trailing\\` case above",
)
def test_the_printed_data_dir_survives_a_directory_that_ends_in_a_separator(monkeypatch):
    """A drive root resolves to `D:\\`, and its trailing backslash escapes the
    closing quote of a naively quoted argument — so the rest of the line, the
    subcommand included, is swallowed into the directory value.

    Reachable by hand (`init --data-dir D:\\`), and not reachable through a
    tmp_path, which is why this goes at the argument rather than at `init`.
    """
    root = Path(Path(sys.executable).anchor)
    monkeypatch.setattr(config_mod, "DEFAULT_DATA_DIR", str(root / "not-this-one"))

    line = f"skill-mcp {config_mod.scope_flag(root)}build-index"

    for shell, split in _shell_parsers().items():
        argv = split(line)
        assert Path(argv[2]) == root, (shell, line, argv)
        assert argv[3:] == ["build-index"], (shell, line, argv)


def test_init_records_a_data_dir_that_still_resolves_from_another_cwd(tmp_path, monkeypatch):
    """`--data-dir ./data` is resolved against the cwd `init` ran in, but the
    config recording it is read from wherever the agent or the user later is.

    Recorded verbatim, it names a different directory there — or none — which is
    the same silent miss the registered argv was just fixed to avoid, left open
    for anyone who types a relative path.
    """
    from click.testing import CliRunner

    from skill_mcp.config import load_config

    home = tmp_path / "home"
    home.mkdir()
    (tmp_path / "here").mkdir()
    (tmp_path / "there").mkdir()
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path / "here")

    CliRunner().invoke(
        cli.main, ["init", "--data-dir", "./data", "--no-register"], catch_exceptions=False
    )
    written = (tmp_path / "here" / "data" / "config.yaml").read_text(encoding="utf-8")
    assert written

    monkeypatch.chdir(tmp_path / "there")
    config = load_config(tmp_path / "here" / "data" / "config.yaml")
    assert config.resolved_data_dir.resolve() == (tmp_path / "here" / "data").resolve()


def test_init_keeps_a_home_relative_data_dir_portable(tmp_path, monkeypatch):
    """`~` resolves per-machine, which is the point on a synced dotfile — so the
    fix for a relative path must not flatten the default into one machine's home.
    """
    from click.testing import CliRunner

    from skill_mcp.config import load_config

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOME", str(home))

    CliRunner().invoke(cli.main, ["init", "--no-register"], catch_exceptions=False)

    config = load_config(home / ".skill-mcp" / "config.yaml")
    assert config.data_dir.startswith("~"), config.data_dir


def test_codex_registration_survives_a_windows_command_path(tmp_path):
    """TOML interprets backslash escapes inside a basic string, so a Windows
    path written verbatim makes the file unparseable: `C:\\Users` opens a
    unicode escape that never completes.

    The registered command is a resolved absolute path, which makes this the
    ordinary case on Windows rather than an exotic one — and the damage lands on
    Codex's whole config, not just on our entry.
    """
    config = tmp_path / "config.toml"
    command = r"C:\Users\v-zhancheng\venv\Scripts\skill-mcp.exe"
    args = ["--data-dir", r"C:\Users\v-zhancheng\.skill-mcp", "serve"]

    cli._register_codex_toml(config, "skill-retrieval", {"command": command, "args": args})

    data = tomllib.loads(config.read_text(encoding="utf-8"))
    assert data["mcp_servers"]["skill-retrieval"]["command"] == command
    assert data["mcp_servers"]["skill-retrieval"]["args"] == args


def test_deepseek_snippet_survives_an_apostrophe_in_the_command_path(tmp_path, monkeypatch, capsys):
    """The snippet quotes the command, and a single-quoted YAML scalar is ended
    by the first apostrophe — which Windows account names such as `O'Brien` put
    straight into the resolved path.
    """
    import yaml

    dsh = tmp_path / "dsh"
    dsh.mkdir()
    monkeypatch.setenv("DSH_HOME", str(dsh))
    command = r"C:\Users\O'Brien\venv\Scripts\skill-mcp.exe"
    args = ["--data-dir", r"C:\Users\O'Brien\.skill-mcp", "serve"]

    cli._print_dsh_snippet({"command": command, "args": args})

    snippet = capsys.readouterr().out.split("cordis.patch.yml", 1)[1].split("\n", 1)[1]
    (op,) = yaml.safe_load(snippet)
    (row,) = op["insert"]
    assert row["config"]["command"] == command
    assert row["config"]["args"] == args


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
