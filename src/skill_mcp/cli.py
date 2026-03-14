"""CLI entry point for skill-retrieval-mcp."""

from __future__ import annotations

import json
from pathlib import Path

import click


@click.group()
def main():
    """skill-retrieval-mcp: RAG-based skill retrieval for AI agents."""
    pass


@main.command()
@click.option("--data-dir", default="~/.skill-mcp", help="Data directory")
@click.option("--no-register", is_flag=True, help="Skip MCP agent registration")
def init(data_dir: str, no_register: bool):
    """Initialize skill-retrieval-mcp data directory and config."""
    from skill_mcp.config import Config, EmbeddingConfig, SearchConfig, ServerConfig, save_config
    from skill_mcp.store import SkillStore

    data_path = Path(data_dir).expanduser()
    data_path.mkdir(parents=True, exist_ok=True)

    config = Config(data_dir=data_dir)
    save_config(config)
    click.echo(f"Config saved to {config.config_path}")

    # Create empty database
    db_path = data_path / "skills.db"
    if not db_path.exists():
        store = SkillStore(db_path)
        store.close()
        click.echo(f"Database created at {db_path}")
    else:
        click.echo(f"Database already exists at {db_path}")

    # Offer to register MCP server
    if not no_register:
        _try_register_mcp(data_path)

    click.echo("\nInitialization complete! Next steps:")
    click.echo("  1. skill-mcp import --source directory --path <skills-dir>")
    click.echo("  2. skill-mcp build-index --backend sentence-transformers")


def _try_register_mcp(data_path: Path) -> None:
    """Try to register the MCP server with known agents."""
    mcp_entry = {
        "command": "skill-mcp",
        "args": ["serve"],
    }

    # Claude Code
    claude_settings = Path("~/.claude/settings.json").expanduser()
    if claude_settings.parent.exists():
        if click.confirm("Register MCP server with Claude Code?", default=True):
            _register_mcp_json(claude_settings, "skill-retrieval", mcp_entry)

    # Cursor
    cursor_mcp = Path(".cursor/mcp.json")
    if cursor_mcp.parent.exists():
        if click.confirm("Register MCP server with Cursor?", default=True):
            _register_mcp_json(cursor_mcp, "skill-retrieval", mcp_entry)


def _register_mcp_json(path: Path, name: str, entry: dict) -> None:
    """Add an MCP server entry to a JSON config file."""
    if path.exists():
        with open(path) as f:
            data = json.load(f)
    else:
        data = {}

    if "mcpServers" not in data:
        data["mcpServers"] = {}

    data["mcpServers"][name] = entry

    with open(path, "w") as f:
        json.dump(data, f, indent=2)

    click.echo(f"  Registered in {path}")


@main.command("import")
@click.option(
    "--source",
    type=click.Choice(["langskills", "skillnet", "anthropic", "directory"]),
    required=True,
)
@click.option("--path", "source_path", type=click.Path(exists=True), required=True)
@click.option("--db", type=click.Path(), default=None, help="Database path (default: ~/.skill-mcp/skills.db)")
def import_skills(source: str, source_path: str, db: str | None):
    """Import skills from a source into the store."""
    from skill_mcp.config import load_config
    from skill_mcp.store import SkillStore

    if db is None:
        config = load_config()
        db = str(config.db_path)

    store = SkillStore(db)
    path = Path(source_path)

    if source == "directory":
        from skill_mcp.importers.directory import DirectoryImporter
        importer = DirectoryImporter()
    elif source == "langskills":
        from skill_mcp.importers.langskills import LangSkillsImporter
        importer = LangSkillsImporter()
    elif source == "skillnet":
        from skill_mcp.importers.skillnet import SkillNetImporter
        importer = SkillNetImporter()
    elif source == "anthropic":
        from skill_mcp.importers.anthropic import AnthropicImporter
        importer = AnthropicImporter()
    else:
        click.echo(f"Unknown source: {source}")
        return

    stats = importer.import_skills(path, store)
    click.echo(f"Imported: {stats.added} added, {stats.replaced} replaced, {stats.skipped_duplicate} duplicates")
    click.echo(f"Store now has {store.count()} skills")
    store.close()


@main.command("build-index")
@click.option("--backend", default="sentence-transformers", help="Embedding backend")
@click.option("--model", default=None, help="Embedding model name")
@click.option("--db", type=click.Path(), default=None)
@click.option("--output", type=click.Path(), default=None, help="Index output directory")
@click.option("--force", is_flag=True, help="Overwrite existing index")
def build_index(backend: str, model: str | None, db: str | None, output: str | None, force: bool):
    """Build FAISS vector index from skill store."""
    from skill_mcp.config import load_config
    from skill_mcp.embeddings import EmbeddingModel
    from skill_mcp.index import SkillIndex
    from skill_mcp.store import SkillStore

    config = load_config()
    if db is None:
        db = str(config.db_path)
    if output is None:
        output = str(config.index_dir)
    if model is None:
        model = config.embedding.model

    output_path = Path(output)
    if (output_path / "index.faiss").exists() and not force:
        click.echo(f"Index already exists at {output_path}. Use --force to overwrite.")
        return

    store = SkillStore(db)
    skill_count = store.count()
    if skill_count == 0:
        click.echo("No skills in store. Import skills first.")
        store.close()
        return

    click.echo(f"Building index for {skill_count} skills with {backend}/{model}...")
    emb = EmbeddingModel(model_name=model, backend=backend)
    index = SkillIndex(emb.dimension)
    index.build(store, emb)
    index.save(output_path)

    click.echo(f"Index built with {len(index.skill_ids)} skills, saved to {output_path}")
    store.close()


@main.command()
@click.option("--transport", default="stdio", type=click.Choice(["stdio", "sse"]))
def serve(transport: str):
    """Start the MCP server."""
    import asyncio
    from skill_mcp.server import run_server
    asyncio.run(run_server())


@main.command()
def status():
    """Show status of skill-retrieval-mcp."""
    from skill_mcp.config import load_config

    config = load_config()
    data_dir = config.resolved_data_dir

    click.echo(f"Data directory: {data_dir}")
    click.echo(f"Config: {config.config_path} ({'exists' if config.config_path.exists() else 'missing (using defaults)'})")

    db_path = config.db_path
    if db_path.exists():
        from skill_mcp.store import SkillStore
        store = SkillStore(db_path, readonly=True)
        click.echo(f"Skills: {store.count()}")
        cats = store.categories()
        if cats:
            click.echo(f"Categories: {', '.join(cats)}")
        store.close()
    else:
        click.echo("Database: not found")

    index_path = config.index_dir / "index.faiss"
    if index_path.exists():
        click.echo(f"Index: built ({index_path})")
    else:
        click.echo("Index: not built")

    click.echo(f"Embedding: {config.embedding.backend}/{config.embedding.model}")


@main.command()
@click.argument("query")
@click.option("--k", default=5, help="Number of results")
def search(query: str, k: int):
    """Search for skills locally (for testing)."""
    from skill_mcp.config import load_config
    from skill_mcp.embeddings import EmbeddingModel
    from skill_mcp.index import SkillIndex
    from skill_mcp.retriever import retrieve
    from skill_mcp.store import SkillStore

    config = load_config()
    store = SkillStore(config.db_path, readonly=True)

    index_dir = config.index_dir
    if not (index_dir / "index.faiss").exists():
        click.echo("No index found. Run `skill-mcp build-index` first.")
        click.echo("Falling back to keyword search...")
        results = store.search_keyword(query, limit=k)
        for i, s in enumerate(results, 1):
            click.echo(f"  {i}. {s.name}: {s.description}")
        store.close()
        return

    index = SkillIndex.load(index_dir)
    emb = EmbeddingModel(
        model_name=config.embedding.model,
        backend=config.embedding.backend,
    )

    results = retrieve(query, store, index, emb, k=k)
    for i, r in enumerate(results, 1):
        click.echo(f"  {i}. [{r.score:.4f}] {r.skill.name}: {r.skill.description}")
    store.close()


@main.command()
@click.option("--db", type=click.Path(), default=None)
def dedup(db: str | None):
    """Run cross-source deduplication on the skill store."""
    from skill_mcp.config import load_config
    from skill_mcp.dedup import deduplicate_skills
    from skill_mcp.store import SkillStore

    if db is None:
        config = load_config()
        db = str(config.db_path)

    store = SkillStore(db)
    before = store.count()
    all_skills = store.get_all()
    deduped = deduplicate_skills(all_skills)

    if len(deduped) == before:
        click.echo(f"No duplicates found. Store has {before} skills.")
        store.close()
        return

    keep_ids = {s.id for s in deduped}
    removed = 0
    for skill in all_skills:
        if skill.id not in keep_ids:
            store.delete_skill(skill.id)
            removed += 1

    click.echo(f"Removed {removed} duplicates. Store: {before} -> {store.count()} skills.")
    store.close()


if __name__ == "__main__":
    main()
