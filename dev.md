# Developer Guide

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                      CLI (cli.py)                       │
│  init · pull · import · build-index · search · status   │
└────────────┬───────────────────────────────┬────────────┘
             │                               │
┌────────────▼────────────┐    ┌─────────────▼────────────┐
│    MCP Server           │    │    Config (config.py)     │
│    (server.py)          │    │    YAML ↔ dataclass       │
│  search_skills          │    │    data_dir / embedding / │
│  get_skill              │    │    server / search        │
│  keyword_search         │    └──────────────────────────┘
│  list_categories        │
└────┬──────┬─────────────┘
     │      │
┌────▼──┐ ┌─▼───────────────────┐
│Store  │ │ SkillIndex (index.py)│
│SQLite │ │ FAISS IndexFlatIP    │
│+ FTS5 │ │ + skill_ids.json     │
└───────┘ └──────┬───────────────┘
                 │
          ┌──────▼──────────────┐
          │ EmbeddingModel      │
          │ (embeddings.py)     │
          │ ST / OpenAI / Ollama│
          └─────────────────────┘
```

Total: **~1750 lines** across 16 source files.

## Module Responsibilities

| Module | Lines | Role |
|--------|-------|------|
| `cli.py` | 494 | CLI commands, orchestration, no business logic |
| `store.py` | 250 | SQLite CRUD + FTS5, dedup-on-insert, merge |
| `server.py` | 240 | MCP protocol handlers, read-only runtime |
| `index.py` | 141 | FAISS build/update/search/save/load |
| `embeddings.py` | 111 | Backend abstraction (ST, OpenAI, Ollama, mock) |
| `config.py` | 109 | YAML config with computed paths |
| `schema.py` | 87 | `Skill` dataclass, deterministic ID/hash |
| `hub.py` | 58 | HuggingFace download (DB + index) |
| `retriever.py` | 37 | query → embed → FAISS search → store lookup |
| `dedup.py` | 28 | Source-priority dedup by content_hash |
| `importers/` | ~120 | Directory, LangSkills, Anthropic parsers |

## Data Model

### Skill

```
id            = sha256(f"{source}:{name}:{content_hash[:8]}")[:16]
content_hash  = md5(instructions)
```

- `id` is deterministic: same source + name + content → same ID
- `content_hash` drives dedup: same instructions = same hash regardless of source/name
- `to_embedding_text()` = `name\ndescription\ninstructions[:500]` — truncated for embedding efficiency

### SQLite Schema

```sql
skills (id PK, name, description, instructions, source, source_id,
        category, tags JSON, metadata JSON, content_hash, created_at)

-- Indexes: source, category, content_hash
-- FTS5 virtual table synced via AFTER INSERT/DELETE triggers
```

### FAISS Index

- `IndexFlatIP` (inner product) with L2-normalized vectors = cosine similarity
- Metadata: `skill_ids.json` = `{skill_ids: [...], dimension: int, embedding: {backend, model}}`
- No deletion support in FAISS → deletions require full rebuild

## Key Design Decisions

### Dedup happens at insert time, not as a batch

`_add_skill_detail` checks `content_hash` before every insert. If a match exists, source priority decides:

```
ANTHROPIC(4) > COMMUNITY(3) > LANGSKILLS(2) > SKILLNET(1)
```

Higher priority replaces lower. Equal or lower is silently skipped. This means the `dedup` CLI command only catches duplicates injected via raw SQL (bypassing `_add_skill_detail`).

### Commit strategy: batch, not per-row

`_add_skill_detail` does NOT commit. Public methods (`add_skill`, `add_skills`, `merge_from`) commit once after all mutations. This makes `merge_from` with 89K skills ~100x faster than per-row commits (one fsync vs 89K).

### Incremental indexing

`SkillIndex.update()` computes `store_ids - indexed_ids`:
- Empty diff → "up to date" (0)
- New IDs → encode only delta, `index.add()` appends (-1 if deletions detected, triggering full rebuild)
- FAISS `IndexFlatIP.add()` supports append but not removal

### Embedding consistency

One index = one embedding model. Enforced at three levels:
1. `build-index` checks `index.embedding_info` against requested backend/model
2. `serve` reads backend/model from index metadata, not config
3. `pull --include-index` verifies downloaded index matches config

Config is the source of truth for *defaults*. Index metadata is the source of truth for *what was actually used*.

### Pull: copy vs merge

```
pull
 ├─ DB doesn't exist / empty / --replace → shutil.copy2 (fast path)
 └─ DB has skills → merge_from (preserves custom skills)
```

After copy, `_rebuild_fts` creates FTS tables + triggers via `SkillStore._init_db` (single source of truth for schema), then triggers `INSERT INTO skills_fts(skills_fts) VALUES('rebuild')`.

### FTS5 content-sync

The FTS table is a content-sync table (`content='skills'`). Triggers keep it in sync:
- `AFTER INSERT` → adds to FTS
- `AFTER DELETE` → removes from FTS

Schema is defined once in `SkillStore._init_db`. `_rebuild_fts` reuses it by constructing a `SkillStore`, which calls `_init_db`, then triggers a full rebuild command.

## Extension Points

### Adding a new embedding backend

1. Add branch in `EmbeddingModel.__init__` and `encode`
2. Add optional dependency in `pyproject.toml`
3. That's it — no other files need changes

### Adding a new importer

1. Create `importers/myformat.py` implementing `BaseImporter` protocol
2. Add CLI branch in `import_skills` command
3. Add source type to `click.Choice`

### Adding a new MCP tool

1. Add `Tool` to `list_tools()` in `server.py`
2. Add handler function `_handle_*` with `_store` null check
3. Add dispatch in `call_tool()`

### Adding a new skill source

1. Add variant to `SkillSource` enum in `schema.py`
2. Add priority in `dedup.py:_SOURCE_PRIORITY`

## Config

```yaml
data_dir: ~/.skill-mcp         # all data lives here
embedding:
  backend: sentence-transformers
  model: all-MiniLM-L6-v2
server:
  transport: stdio
  name: skill-retrieval
search:
  default_k: 5
```

Resolution order: CLI `--data-dir` → env `SKILL_MCP_DATA_DIR` → config.yaml `data_dir` → default `~/.skill-mcp`

Config is saved by `build-index` (to record which backend/model was used). Never overwritten by `pull`.

## File Layout

```
~/.skill-mcp/
├── config.yaml
├── skills.db          # SQLite + FTS5
└── index/
    ├── index.faiss    # FAISS binary
    └── skill_ids.json # IDs + dimension + embedding info
```

## Testing

```bash
pytest tests/test_workflow.py -v    # 110 tests, ~0.7s
```

Tests use `--backend mock` (deterministic hash-based 128-dim embeddings, no model download). Key test categories:

| Category | Count | What it covers |
|----------|-------|----------------|
| E2E workflow | 15 | init → import → build → search lifecycle |
| Cross-feature | 9 | pull+import+build, incremental, dedup+rebuild |
| Server handlers | 11 | null store, invalid IDs, special chars, k=0 |
| Store edge cases | 14 | merge priority, empty source, FTS sync |
| Index | 12 | incremental, deletion detection, save/load, empty |
| Pull command | 8 | merge, replace, dedup, fast path, stale index |
| Schema/Config/FTS | 12 | partial YAML, roundtrip, special chars |
| Others | 29 | importers, dedup, embedding model, data-dir |

## MCP Tool Interface

### search_skills

```json
{"query": "debug memory leak", "k": 3}
→ [{"id": "a1b2", "name": "...", "description": "...", "score": 0.81, "category": "...", "tags": [...]}]
```

Returns summaries only (no `instructions`) to save context tokens.

### get_skill

```json
{"skill_id": "a1b2"}
→ {"id": "...", "name": "...", "instructions": "full text...", ...}
```

Returns full instructions. Call after `search_skills` for the skills you need.

### keyword_search

```json
{"query": "docker deploy", "limit": 10}
→ [{"id": "...", "name": "...", "description": "...", ...}]
```

FTS5 text search. Works without vector index. Handles special characters via automatic escaping.

### list_categories

```json
{}
→ [{"category": "debugging", "count": 42}, ...]
```

## Dependencies

Core (always installed): `mcp`, `faiss-cpu`, `numpy`, `click`, `pyyaml`, `tqdm`

Optional:
- `[local]` — `sentence-transformers` (default embedding backend)
- `[openai]` — `openai`, `tiktoken`
- `[ollama]` — `httpx`
- `[hf]` — `huggingface-hub` (for `pull`)
- `[sse]` — `starlette`, `uvicorn` (SSE transport)
- `[all]` — everything above
- `[dev]` — `pytest`, `pytest-asyncio`, `ruff`
