"""Configuration for skill-retrieval-mcp."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


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
    data_dir: str = "~/.skill-mcp"
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


def load_config(config_path: Path | None = None) -> Config:
    """Load config from YAML file, falling back to defaults."""
    if config_path is None:
        config_path = Path("~/.skill-mcp/config.yaml").expanduser()

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
