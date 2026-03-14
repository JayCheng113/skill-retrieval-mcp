"""CLI entry point for skill-retrieval-mcp."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import click


@click.group()
@click.option(
    "--data-dir",
    "global_data_dir",
    default=None,
    envvar="SKILL_MCP_DATA_DIR",
    help="Override data directory (default: ~/.skill-mcp, env: SKILL_MCP_DATA_DIR)",
)
@click.option(
    "--log-level",
    default=None,
    envvar="SKILL_MCP_LOG_LEVEL",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"], case_sensitive=False),
    help="Log level (default: WARNING, env: SKILL_MCP_LOG_LEVEL)",
)
@click.pass_context
def main(ctx, global_data_dir: str | None, log_level: str | None):
    """skill-retrieval-mcp: RAG-based skill retrieval for AI agents."""
    ctx.ensure_object(dict)
    ctx.obj["data_dir"] = global_data_dir

    if log_level:
        logging.basicConfig(
            level=getattr(logging, log_level.upper()),
            format="%(asctime)s %(name)s %(levelname)s %(message)s",
            datefmt="%H:%M:%S",
        )


def _load_config_from_ctx(ctx):
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
    from skill_mcp.config import Config, save_config
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
    click.echo("    skill-mcp pull --include-index")
    click.echo("  Option B (import your own skills):")
    click.echo("    skill-mcp import --source directory --path <skills-dir>")
    click.echo("    (index is built automatically after import)")


def _try_register_mcp(data_path: Path) -> None:
    """Try to register the MCP server with known agents."""
    mcp_entry = {
        "command": "skill-mcp",
        "args": ["serve"],
    }

    # Claude Code — project-level .mcp.json
    claude_mcp = Path(".mcp.json")
    if click.confirm("Register with Claude Code (.mcp.json)?", default=True):
        _register_mcp_json(claude_mcp, "skill-retrieval", mcp_entry)

    # Gemini CLI — ~/.gemini/settings.json
    gemini_dir = Path("~/.gemini").expanduser()
    if gemini_dir.exists():
        if click.confirm("Register with Gemini CLI (~/.gemini/settings.json)?", default=True):
            _register_mcp_json(gemini_dir / "settings.json", "skill-retrieval", mcp_entry)

    # Cursor — .cursor/mcp.json
    cursor_dir = Path(".cursor")
    if cursor_dir.exists():
        if click.confirm("Register with Cursor (.cursor/mcp.json)?", default=True):
            _register_mcp_json(cursor_dir / "mcp.json", "skill-retrieval", mcp_entry)

    # Codex CLI — ~/.codex/config.toml
    codex_config = Path("~/.codex/config.toml").expanduser()
    if codex_config.parent.exists():
        if click.confirm("Register with Codex CLI (~/.codex/config.toml)?", default=True):
            _register_codex_toml(codex_config, "skill-retrieval", mcp_entry)


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


def _register_codex_toml(path: Path, name: str, entry: dict) -> None:
    """Add an MCP server entry to Codex CLI's TOML config."""
    import tomllib

    existing = ""
    if path.exists():
        existing = path.read_text()
        # Check if already registered
        try:
            data = tomllib.loads(existing)
            if name in data.get("mcp_servers", {}):
                click.echo(f"  Already registered in {path}")
                return
        except Exception:
            pass

    section = f'\n[mcp_servers.{name}]\ncommand = "{entry["command"]}"\nargs = {json.dumps(entry["args"])}\n'
    with open(path, "a") as f:
        f.write(section)
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
        click.echo(
            f"Merged: {stats.added:,} new, {stats.replaced:,} upgraded, {stats.skipped_duplicate:,} unchanged"
        )
        click.echo(f"Store: {before:,} -> {store.count():,} skills")
        store.close()

    # Warn about stale index (after both copy and merge paths)
    index_path = config.index_dir / "index.faiss"
    if include_index:
        _pull_index(config)
    elif index_path.exists() and not replace:
        click.echo("Note: run `skill-mcp build-index` to update the index.")
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
    """Rebuild FTS index after copying a database file.

    Uses SkillStore._init_db to ensure FTS schema stays in sync,
    then triggers a full FTS rebuild.
    """
    from skill_mcp.store import SkillStore

    store = SkillStore(db_path)  # _init_db creates FTS tables + triggers if missing
    store._conn.execute("INSERT INTO skills_fts(skills_fts) VALUES('rebuild')")
    store._conn.commit()
    store.close()


def _pull_index(config) -> None:
    """Download pre-built index matching the configured embedding backend."""
    import shutil

    from skill_mcp.hub import download_index

    backend = config.embedding.backend
    model = config.embedding.model
    click.echo(f"Downloading pre-built index ({backend}/{model})...")
    try:
        index_files = download_index(backend=backend, model=model)
    except FileNotFoundError as e:
        click.echo(str(e))
        return

    # Verify downloaded index matches expected embedding
    with open(index_files["meta"]) as f:
        meta = json.load(f)
    dl_emb = meta.get("embedding", {})
    dl_backend = dl_emb.get("backend", "")
    dl_model = dl_emb.get("model", "")
    if dl_backend and dl_backend != backend:
        click.echo(
            f"WARNING: downloaded index uses {dl_backend}/{dl_model} "
            f"but your config expects {backend}/{model}.\n"
            f"Run `skill-mcp build-index` to build a compatible index locally."
        )
        return

    index_dir = config.index_dir
    index_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(index_files["faiss"], index_dir / "index.faiss")
    shutil.copy2(index_files["meta"], index_dir / "skill_ids.json")

    index_count = len(meta.get("skill_ids", []))
    click.echo(f"Index: {index_count:,} vectors ({dl_backend}/{dl_model})")

    # Check if store has skills not covered by the index
    from skill_mcp.store import SkillStore

    if config.db_path.exists():
        store = SkillStore(config.db_path, readonly=True)
        db_count = store.count()
        store.close()
        if db_count > index_count:
            click.echo(f"  Note: store has {db_count - index_count:,} skills not in index.")
            click.echo("  Run `skill-mcp build-index` to include all.")


@main.command("import")
@click.option(
    "--source",
    type=click.Choice(["langskills", "anthropic", "directory"]),
    required=True,
)
@click.option("--path", "source_path", type=click.Path(exists=True), required=True)
@click.option(
    "--db", type=click.Path(), default=None, help="Database path (default: ~/.skill-mcp/skills.db)"
)
@click.option(
    "--no-index", is_flag=True, help="Skip automatic index update after import"
)
@click.pass_context
def import_skills(ctx, source: str, source_path: str, db: str | None, no_index: bool):
    """Import skills from a source into the store.

    After importing, automatically updates the vector index so new skills
    are immediately searchable. Use --no-index to skip this (e.g. when
    batch-importing from multiple sources before a single build).
    """
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
    click.echo(
        f"Imported: {stats.added} added, {stats.replaced} replaced, {stats.skipped_duplicate} duplicates"
    )
    click.echo(f"Store now has {store.count()} skills")

    new_skills = stats.added > 0 or stats.replaced > 0
    if new_skills and not no_index:
        _auto_index(config, store)
    elif new_skills and no_index:
        if config.index_dir.exists() and (config.index_dir / "index.faiss").exists():
            click.echo("Index update skipped (--no-index). Run `skill-mcp build-index` when ready.")

    store.close()


def _auto_index(config, store) -> None:
    """Automatically update the vector index after import.

    Only runs if an index already exists (meaning the user has a working
    embedding setup). If no index exists, prompts the user to build one.
    """
    from skill_mcp.embeddings import EmbeddingModel
    from skill_mcp.index import SkillIndex

    backend = config.embedding.backend
    model = config.embedding.model
    index_dir = config.index_dir
    existing_index = index_dir / "index.faiss"

    if not existing_index.exists():
        click.echo("No index found. Run `skill-mcp build-index` to make skills searchable.")
        return

    index = SkillIndex.load(index_dir)
    emb_info = index.embedding_info
    if emb_info.get("backend") != backend or emb_info.get("model") != model:
        click.echo(
            f"Index uses {emb_info.get('backend')}/{emb_info.get('model')} "
            f"but config expects {backend}/{model}. Skipping auto-index."
        )
        click.echo("Run `skill-mcp build-index --force` to rebuild with the new model.")
        return

    emb = EmbeddingModel(model_name=model, backend=backend)
    added = index.update(store, emb)
    if added == 0:
        click.echo(f"Index is up to date ({len(index.skill_ids)} skills).")
    elif added > 0:
        index.save(index_dir)
        click.echo(f"Index updated: {added} new skills indexed (total {len(index.skill_ids)}).")
    else:
        # added == -1: deletions detected, full rebuild needed
        click.echo("Skills were removed. Rebuilding index...")
        _full_build(config, store, backend, model)


def _full_build(config, store, backend: str, model: str) -> None:
    """Full index build helper for _auto_index."""
    from skill_mcp.config import save_config
    from skill_mcp.embeddings import EmbeddingModel
    from skill_mcp.index import SkillIndex

    emb = EmbeddingModel(model_name=model, backend=backend)
    index = SkillIndex(emb.dimension)
    index.embedding_info = {"backend": backend, "model": model}
    index.build(store, emb)
    index.save(config.index_dir)

    config.embedding.backend = backend
    config.embedding.model = model
    save_config(config)

    click.echo(f"Index built: {len(index.skill_ids)} skills.")


@main.command("build-index")
@click.option("--backend", default=None, help="Embedding backend (default: from config)")
@click.option("--model", default=None, help="Embedding model name (default: from config)")
@click.option("--db", type=click.Path(), default=None)
@click.option("--output", type=click.Path(), default=None, help="Index output directory")
@click.option("--force", is_flag=True, help="Overwrite existing index")
@click.pass_context
def build_index(
    ctx, backend: str, model: str | None, db: str | None, output: str | None, force: bool
):
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
    if backend is None:
        backend = config.embedding.backend
    if model is None:
        model = config.embedding.model

    output_path = Path(output)
    store = SkillStore(db)
    skill_count = store.count()
    if skill_count == 0:
        click.echo("No skills in store. Import skills first.")
        store.close()
        return

    existing_index = output_path / "index.faiss"

    # Try incremental update if index exists and --force not set
    if existing_index.exists() and not force:
        index = SkillIndex.load(output_path)
        emb_info = index.embedding_info
        if emb_info.get("backend") != backend or emb_info.get("model") != model:
            click.echo(
                f"Embedding model changed ({emb_info.get('backend')}/{emb_info.get('model')} -> {backend}/{model})."
            )
            click.echo("Use --force to rebuild with the new model.")
            store.close()
            return

        emb = EmbeddingModel(model_name=model, backend=backend)
        added = index.update(store, emb)
        if added == 0:
            click.echo(f"Index is up to date ({len(index.skill_ids)} skills).")
            store.close()
            return
        if added > 0:
            index.save(output_path)
            click.echo(f"Incremental update: added {added} skills (total {len(index.skill_ids)}).")
            store.close()
            return
        # added == -1: deletions detected, fall through to full rebuild
        click.echo("Skills were removed from store. Rebuilding full index...")

    click.echo(f"Building index for {skill_count} skills with {backend}/{model}...")
    emb = EmbeddingModel(model_name=model, backend=backend)
    index = SkillIndex(emb.dimension)
    index.embedding_info = {"backend": backend, "model": model}
    index.build(store, emb)
    index.save(output_path)

    config.embedding.backend = backend
    config.embedding.model = model
    save_config(config)

    click.echo(f"Index built: {len(index.skill_ids)} skills, saved to {output_path}")
    store.close()


@main.command()
@click.option("--transport", default="stdio", type=click.Choice(["stdio", "sse"]))
@click.pass_context
def serve(ctx, transport: str):
    """Start the MCP server."""
    import asyncio
    from skill_mcp.server import run_server

    # Default to INFO for serve if no explicit --log-level
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(name)s %(levelname)s %(message)s",
            datefmt="%H:%M:%S",
        )

    config = _load_config_from_ctx(ctx)
    asyncio.run(run_server(config_path=config.config_path, transport=transport))


@main.command()
@click.pass_context
def status(ctx):
    """Show status of skill-retrieval-mcp."""
    config = _load_config_from_ctx(ctx)
    data_dir = config.resolved_data_dir

    click.echo(f"Data directory: {data_dir}")
    click.echo(
        f"Config: {config.config_path} ({'exists' if config.config_path.exists() else 'missing (using defaults)'})"
    )

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
            click.echo(
                f"  WARNING: index ({index_count}) != store ({db_count}). Run `skill-mcp build-index`."
            )
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
