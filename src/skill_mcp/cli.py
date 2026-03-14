"""CLI entry point for skill-retrieval-mcp."""

from __future__ import annotations

import json
from pathlib import Path

import click


@click.group()
@click.option("--data-dir", "global_data_dir", default=None, envvar="SKILL_MCP_DATA_DIR",
              help="Override data directory (default: ~/.skill-mcp, env: SKILL_MCP_DATA_DIR)")
@click.pass_context
def main(ctx, global_data_dir: str | None):
    """skill-retrieval-mcp: RAG-based skill retrieval for AI agents."""
    ctx.ensure_object(dict)
    ctx.obj["data_dir"] = global_data_dir


def _load_config_from_ctx(ctx) -> "Config":
    """Load config, respecting the global --data-dir override."""
    from skill_mcp.config import load_config

    data_dir = ctx.obj.get("data_dir") if ctx.obj else None
    if data_dir:
        config_path = Path(data_dir).expanduser() / "config.yaml"
        config = load_config(config_path)
        config.data_dir = data_dir
        return config
    return load_config()


@main.command()
@click.option("--data-dir", default=None, help="Data directory (default: ~/.skill-mcp)")
@click.option("--no-register", is_flag=True, help="Skip MCP agent registration")
@click.pass_context
def init(ctx, data_dir: str | None, no_register: bool):
    """Initialize skill-retrieval-mcp data directory and config."""
    from skill_mcp.config import Config, EmbeddingConfig, SearchConfig, ServerConfig, save_config
    from skill_mcp.store import SkillStore

    # Global --data-dir takes precedence, then local --data-dir, then default
    global_dir = ctx.obj.get("data_dir") if ctx.obj else None
    data_dir = global_dir or data_dir or "~/.skill-mcp"
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
    click.echo("  Option A (quick start with 89K pre-built skills):")
    click.echo("    skill-mcp pull")
    click.echo("  Option B (import your own skills):")
    click.echo("    skill-mcp import --source directory --path <skills-dir>")
    click.echo("  Then build the search index:")
    click.echo("    skill-mcp build-index --backend sentence-transformers")


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


@main.command()
@click.option("--replace", is_flag=True, help="Replace existing database entirely (default: merge)")
@click.option("--include-index", is_flag=True, help="Also download pre-built vector index")
@click.pass_context
def pull(ctx, replace: bool, include_index: bool):
    """Download pre-built skill dataset (~89K skills) from HuggingFace.

    By default, merges downloaded skills into your existing store so your
    custom skills are preserved. Use --replace to start fresh.

    \b
    Examples:
      skill-mcp pull                   # Merge HF skills into local store
      skill-mcp pull --include-index   # Also download pre-built vector index
      skill-mcp pull --replace         # Replace local DB entirely
    """
    import shutil

    from skill_mcp.hub import download_skills_db
    from skill_mcp.store import SkillStore

    config = _load_config_from_ctx(ctx)
    data_dir = config.resolved_data_dir

    # Auto-init if needed
    if not data_dir.exists():
        from skill_mcp.config import Config, save_config
        data_dir.mkdir(parents=True, exist_ok=True)
        save_config(Config(data_dir=str(data_dir)))
        click.echo(f"Initialized {data_dir}")

    click.echo("Downloading skills from HuggingFace...")
    cached_db = download_skills_db()
    db_path = config.db_path

    # Decide: copy (fast) vs merge (preserves custom skills)
    local_count = 0
    if db_path.exists():
        probe = SkillStore(db_path, readonly=True)
        local_count = probe.count()
        probe.close()

    if not db_path.exists() or replace or local_count == 0:
        # Fast path: no local data, empty DB, or explicit replace — copy directly
        shutil.copy2(cached_db, db_path)
        _rebuild_fts(db_path)
        store = SkillStore(db_path, readonly=True)
        click.echo(f"Loaded {store.count():,} skills")
        store.close()
    else:
        # Merge: preserve existing custom skills
        store = SkillStore(db_path)
        before = store.count()
        stats = store.merge_from(cached_db)
        click.echo(f"Merged: {stats.added:,} new, {stats.replaced:,} upgraded, {stats.skipped_duplicate:,} unchanged")
        click.echo(f"Store: {before:,} -> {store.count():,} skills")
        store.close()

    # Warn about stale index (after both copy and merge paths)
    index_path = config.index_dir / "index.faiss"
    if include_index:
        _pull_index(config)
    elif index_path.exists() and not replace:
        click.echo("Note: index may be stale. Run `skill-mcp build-index --force` to rebuild.")
    else:
        if replace and index_path.exists():
            # Clean stale index after --replace
            index_path.unlink()
            meta = config.index_dir / "skill_ids.json"
            if meta.exists():
                meta.unlink()
            click.echo("Cleared stale index.")
        click.echo("\nNext step:")
        click.echo("  skill-mcp build-index --backend sentence-transformers")


def _rebuild_fts(db_path: Path) -> None:
    """Rebuild FTS index after copying a database file."""
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE VIRTUAL TABLE IF NOT EXISTS skills_fts USING fts5(
            name, description, instructions,
            content='skills', content_rowid='rowid'
        );
        CREATE TRIGGER IF NOT EXISTS skills_ai AFTER INSERT ON skills BEGIN
            INSERT INTO skills_fts(rowid, name, description, instructions)
            VALUES (new.rowid, new.name, new.description, new.instructions);
        END;
        CREATE TRIGGER IF NOT EXISTS skills_ad AFTER DELETE ON skills BEGIN
            INSERT INTO skills_fts(skills_fts, rowid, name, description, instructions)
            VALUES ('delete', old.rowid, old.name, old.description, old.instructions);
        END;
        INSERT INTO skills_fts(skills_fts) VALUES('rebuild');
    """)
    conn.commit()
    conn.close()


def _pull_index(config) -> None:
    """Download pre-built index and check consistency with store."""
    import shutil

    from skill_mcp.hub import download_index

    click.echo("Downloading pre-built index...")
    index_files = download_index()
    index_dir = config.index_dir
    index_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(index_files["faiss"], index_dir / "index.faiss")
    shutil.copy2(index_files["meta"], index_dir / "skill_ids.json")

    with open(index_dir / "skill_ids.json") as f:
        meta = json.load(f)
    index_count = len(meta.get("skill_ids", []))
    emb = meta.get("embedding", {})
    backend = emb.get("backend", "unknown")
    model = emb.get("model", "unknown")
    click.echo(f"Index: {index_count:,} vectors ({backend}/{model})")

    # Sync config with index embedding settings
    if emb:
        from skill_mcp.config import save_config
        config.embedding.backend = backend
        config.embedding.model = model
        save_config(config)

    # Warn if store has skills not covered by the index
    from skill_mcp.store import SkillStore
    if config.db_path.exists():
        store = SkillStore(config.db_path, readonly=True)
        db_count = store.count()
        store.close()
        if db_count > index_count:
            click.echo(f"  Note: store has {db_count - index_count:,} skills not in index.")
            click.echo(f"  Run `skill-mcp build-index --force` to include all.")


@main.command("import")
@click.option(
    "--source",
    type=click.Choice(["langskills", "anthropic", "directory"]),
    required=True,
)
@click.option("--path", "source_path", type=click.Path(exists=True), required=True)
@click.option("--db", type=click.Path(), default=None, help="Database path (default: ~/.skill-mcp/skills.db)")
@click.pass_context
def import_skills(ctx, source: str, source_path: str, db: str | None):
    """Import skills from a source into the store."""
    from skill_mcp.store import SkillStore

    config = _load_config_from_ctx(ctx)
    if db is None:
        db = str(config.db_path)

    store = SkillStore(db)
    path = Path(source_path)

    if source == "directory":
        from skill_mcp.importers.directory import DirectoryImporter
        importer = DirectoryImporter()
    elif source == "langskills":
        from skill_mcp.importers.langskills import LangSkillsImporter
        importer = LangSkillsImporter()
    elif source == "anthropic":
        from skill_mcp.importers.anthropic import AnthropicImporter
        importer = AnthropicImporter()
    else:
        click.echo(f"Unknown source: {source}")
        return

    stats = importer.import_skills(path, store)
    click.echo(f"Imported: {stats.added} added, {stats.replaced} replaced, {stats.skipped_duplicate} duplicates")
    click.echo(f"Store now has {store.count()} skills")
    if (stats.added > 0 or stats.replaced > 0) and (config.index_dir / "index.faiss").exists():
        click.echo("Note: index is now stale. Run `skill-mcp build-index --force` to rebuild.")
    store.close()


@main.command("build-index")
@click.option("--backend", default="sentence-transformers", help="Embedding backend")
@click.option("--model", default=None, help="Embedding model name")
@click.option("--db", type=click.Path(), default=None)
@click.option("--output", type=click.Path(), default=None, help="Index output directory")
@click.option("--force", is_flag=True, help="Overwrite existing index")
@click.pass_context
def build_index(ctx, backend: str, model: str | None, db: str | None, output: str | None, force: bool):
    """Build FAISS vector index from skill store."""
    from skill_mcp.config import save_config
    from skill_mcp.embeddings import EmbeddingModel
    from skill_mcp.index import SkillIndex
    from skill_mcp.store import SkillStore

    config = _load_config_from_ctx(ctx)
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
    index.embedding_info = {"backend": backend, "model": model}
    index.build(store, emb)
    index.save(output_path)

    # Write the actual backend/model used back to config so serve uses the same
    config.embedding.backend = backend
    config.embedding.model = model
    save_config(config)

    click.echo(f"Index built with {len(index.skill_ids)} skills, saved to {output_path}")
    click.echo(f"Config updated: embedding.backend={backend}, embedding.model={model}")
    store.close()


@main.command()
@click.option("--transport", default="stdio", type=click.Choice(["stdio", "sse"]))
@click.pass_context
def serve(ctx, transport: str):
    """Start the MCP server."""
    import asyncio
    from skill_mcp.server import run_server

    config = _load_config_from_ctx(ctx)
    asyncio.run(run_server(config_path=config.config_path, transport=transport))


@main.command()
@click.pass_context
def status(ctx):
    """Show status of skill-retrieval-mcp."""
    config = _load_config_from_ctx(ctx)
    data_dir = config.resolved_data_dir

    click.echo(f"Data directory: {data_dir}")
    click.echo(f"Config: {config.config_path} ({'exists' if config.config_path.exists() else 'missing (using defaults)'})")

    db_path = config.db_path
    db_count = 0
    if db_path.exists():
        from skill_mcp.store import SkillStore
        store = SkillStore(db_path, readonly=True)
        db_count = store.count()
        click.echo(f"Skills: {db_count}")
        cats = store.categories()
        if cats:
            click.echo(f"Categories: {', '.join(cats)}")
        store.close()
    else:
        click.echo("Database: not found (run `skill-mcp init` first)")

    index_path = config.index_dir / "index.faiss"
    meta_path = config.index_dir / "skill_ids.json"
    if index_path.exists() and meta_path.exists():
        with open(meta_path) as f:
            meta = json.load(f)
        index_count = len(meta.get("skill_ids", []))
        click.echo(f"Index: {index_count} skills ({index_path})")
        if db_count > 0 and index_count != db_count:
            click.echo(f"  WARNING: index ({index_count}) != store ({db_count}). Run `skill-mcp build-index --force`.")
    else:
        click.echo("Index: not built")

    click.echo(f"Embedding: {config.embedding.backend}/{config.embedding.model}")


@main.command()
@click.argument("query")
@click.option("--k", default=5, help="Number of results")
@click.pass_context
def search(ctx, query: str, k: int):
    """Search for skills locally (for testing)."""
    from skill_mcp.embeddings import EmbeddingModel
    from skill_mcp.index import SkillIndex
    from skill_mcp.retriever import retrieve
    from skill_mcp.store import SkillStore

    config = _load_config_from_ctx(ctx)

    if not config.db_path.exists():
        click.echo("No skill database found. Run `skill-mcp init` first.")
        return

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
    # Use embedding info from index metadata (matches what was used to build)
    emb_info = index.embedding_info
    emb = EmbeddingModel(
        model_name=emb_info.get("model", config.embedding.model),
        backend=emb_info.get("backend", config.embedding.backend),
    )

    results = retrieve(query, store, index, emb, k=k)
    for i, r in enumerate(results, 1):
        click.echo(f"  {i}. [{r.score:.4f}] {r.skill.name}: {r.skill.description}")
    store.close()


@main.command()
@click.option("--db", type=click.Path(), default=None)
@click.pass_context
def dedup(ctx, db: str | None):
    """Run cross-source deduplication on the skill store."""
    from skill_mcp.dedup import deduplicate_skills
    from skill_mcp.store import SkillStore

    if db is None:
        config = _load_config_from_ctx(ctx)
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
