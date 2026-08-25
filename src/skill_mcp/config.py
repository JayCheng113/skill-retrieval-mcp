"""Configuration for skill-retrieval-mcp."""

from __future__ import annotations

import os
import shlex
from dataclasses import dataclass, field
from pathlib import Path

# `yaml` is imported by the two functions that read and write the file, not here.
# `cli.py` defers its heavy imports to keep startup cheap and reaches into this
# module for `DEFAULT_DATA_DIR` before it knows which command it is running, so a
# module-level `import yaml` would put 17ms of parser on `skill-mcp --help`.

DEFAULT_DATA_DIR = "~/.skill-mcp"


@dataclass
class EmbeddingConfig:
    backend: str = "sentence-transformers"
    model: str = "all-MiniLM-L6-v2"


@dataclass
class ServerConfig:
    transport: str = "stdio"
    name: str = "skill-retrieval"


@dataclass
class SearchConfig:
    default_k: int = 5


@dataclass
class Config:
    data_dir: str = DEFAULT_DATA_DIR
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    search: SearchConfig = field(default_factory=SearchConfig)

    @property
    def resolved_data_dir(self) -> Path:
        return Path(self.data_dir).expanduser()

    @property
    def db_path(self) -> Path:
        return self.resolved_data_dir / "skills.db"

    @property
    def index_dir(self) -> Path:
        return self.resolved_data_dir / "index"

    @property
    def config_path(self) -> Path:
        return self.resolved_data_dir / "config.yaml"


def default_data_dir() -> Path:
    return Path(DEFAULT_DATA_DIR).expanduser().resolve()


def portable_data_dir(data_dir: str, data_path: Path) -> str:
    """What `config.yaml` should record, given what the user typed.

    The file is read from whatever directory the agent or the user is in later,
    so a relative path recorded verbatim names somewhere else there. `~` does
    survive the move — and re-resolving it per machine is the point on a synced
    dotfile — so it is kept as typed.
    """
    if data_dir.startswith("~") or Path(data_dir).is_absolute():
        return data_dir
    return str(data_path)


def scope_flag(data_dir: str | Path) -> str:
    """The `--data-dir` that a printed command carries, quoted to paste.

    Every command we print is pasted verbatim, and this flag is the one part
    that cannot be recovered once dropped: the config recording the choice lives
    inside the chosen directory. A command missing it runs against the default
    one and reports nothing wrong.

    Windows gets forward slashes: a resolved directory can end in a backslash
    (`D:\\`), which escapes the closing quote and swallows the rest of the line
    into the value, and every Windows API accepts `/` anyway. Wrapping is
    unconditional because a double quote cannot appear in a Windows path.

    That covers separators, spaces and apostrophes in every shell a Windows user
    is likely to paste into. It cannot cover a directory whose name expands:
    `%X%` is substituted by cmd inside double quotes, `$X` by PowerShell and Git
    bash, and a backtick starts a substitution in bash and an escape in
    PowerShell. All three are legal in a Windows path and none has a quoting
    that is inert in cmd as well — cmd understands no quote but this one.
    """
    data_path = Path(data_dir).expanduser().resolve()
    if data_path == default_data_dir():
        return ""
    quoted = f'"{data_path.as_posix()}"' if os.name == "nt" else shlex.quote(str(data_path))
    return f"--data-dir {quoted} "


def load_config(config_path: Path | None = None) -> Config:
    """Load config from YAML file, falling back to defaults."""
    import yaml

    if config_path is None:
        config_path = Path(DEFAULT_DATA_DIR).expanduser() / "config.yaml"

    if not config_path.exists():
        return Config()

    with open(config_path) as f:
        raw = yaml.safe_load(f) or {}

    config = Config()

    if "data_dir" in raw:
        config.data_dir = raw["data_dir"]

    emb = raw.get("embedding", {})
    if emb:
        config.embedding = EmbeddingConfig(
            backend=emb.get("backend", config.embedding.backend),
            model=emb.get("model", config.embedding.model),
        )

    srv = raw.get("server", {})
    if srv:
        config.server = ServerConfig(
            transport=srv.get("transport", config.server.transport),
            name=srv.get("name", config.server.name),
        )

    search = raw.get("search", {})
    if search:
        config.search = SearchConfig(
            default_k=search.get("default_k", config.search.default_k),
        )

    return config


def save_config(config: Config) -> None:
    """Save config to YAML file."""
    import yaml

    data = {
        "data_dir": config.data_dir,
        "embedding": {
            "backend": config.embedding.backend,
            "model": config.embedding.model,
        },
        "server": {
            "transport": config.server.transport,
            "name": config.server.name,
        },
        "search": {
            "default_k": config.search.default_k,
        },
    }
    config.config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config.config_path, "w") as f:
        yaml.dump(data, f, default_flow_style=False)
