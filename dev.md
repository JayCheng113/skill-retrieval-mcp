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

~1850 lines across 16 source files.

## Module Responsibilities

| Module | Lines | Role |
|--------|-------|------|
| `cli.py` | 542 | CLI commands, orchestration, no business logic |
| `server.py` | 295 | MCP protocol handlers, server instructions, structured logging, read-only runtime |
| `store.py` | 250 | SQLite CRUD + FTS5, dedup-on-insert, batch commit, merge |
| `index.py` | 139 | FAISS build/update/search/save/load |
| `embeddings.py` | 112 | Backend abstraction (ST, OpenAI, Ollama, mock) |
| `config.py` | 109 | YAML config with computed paths |
| `schema.py` | 89 | `Skill` dataclass, deterministic ID/hash |
| `hub.py` | 60 | HuggingFace download (DB + index by backend/model) |
| `retriever.py` | 37 | query → embed → FAISS search → store lookup |
| `dedup.py` | 28 | Source-priority dedup by content_hash |
| `importers/` | ~130 | Directory, LangSkills, Anthropic parsers + shared frontmatter |

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

### HuggingFace Layout

```
zcheng256/skillretrieval-data (dataset repo)
├── processed/skills.db                                    960MB
├── indices/sentence-transformers/all-MiniLM-L6-v2/        137MB  (384-dim)
│   ├── index.faiss
│   └── skill_ids.json
└── indices/openai/text-embedding-3-large/                 1.1GB  (3072-dim)
    ├── index.faiss
    └── skill_ids.json
```

`pull --include-index` downloads the index matching `config.embedding.backend/model`. `download_index()` in `hub.py` constructs the path as `indices/{backend}/{model}/`.

## Key Design Decisions

### Dedup happens at insert time, not as a batch

`_add_skill_detail` checks `content_hash` before every insert. If a match exists, source priority decides:

```
ANTHROPIC(4) > COMMUNITY(3) > LANGSKILLS(2) > SKILLNET(1)
```

Higher priority replaces lower. Equal or lower is silently skipped. The `dedup` CLI command only catches duplicates injected via raw SQL (bypassing `_add_skill_detail`).

### Commit strategy: batch, not per-row

`_add_skill_detail` does NOT commit. Public methods (`add_skill`, `add_skills`, `merge_from`) commit once after all mutations. This makes `merge_from` with 89K skills ~100x faster than per-row commits (one fsync vs 89K).

### Incremental indexing

`SkillIndex.update()` computes `store_ids - indexed_ids`:
- Empty diff → "up to date" (returns 0)
- New IDs → encode only delta, `index.add()` appends (returns count)
- Indexed IDs missing from store → deletions detected (returns -1, triggers full rebuild)

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

After copy, `_rebuild_fts` reuses `SkillStore._init_db` (single source of truth for FTS schema), then triggers a full FTS rebuild.

### Logging

`server.py` uses Python `logging` module (`logger = logging.getLogger("skill_mcp")`):
- Startup: store/index load status, backend/model, transport
- Each tool call: name + latency in ms
- Warnings: missing store, missing index, skill not found

CLI exposes `--log-level` (or env `SKILL_MCP_LOG_LEVEL`). `serve` defaults to INFO.

## Extension Points

### Adding a new embedding backend

1. Add branch in `EmbeddingModel.__init__` and `encode`
2. Add optional dependency in `pyproject.toml`

### Adding a new importer

1. Create `importers/myformat.py` implementing `BaseImporter` protocol
2. Use `split_frontmatter()` from `importers/frontmatter.py` if parsing SKILL.md
3. Add CLI branch in `import_skills` command + `click.Choice`

### Adding a new MCP tool

1. Add `Tool` to `list_tools()` in `server.py`
2. Add handler function `_handle_*` with `_store` null check
3. Add dispatch in `call_tool()`

### Adding a new skill source

1. Add variant to `SkillSource` enum in `schema.py`
2. Add priority in `dedup.py:_SOURCE_PRIORITY`

## Config

```yaml
data_dir: ~/.skill-mcp
embedding:
  backend: sentence-transformers
  model: all-MiniLM-L6-v2
server:
  transport: stdio
  name: skill-retrieval
search:
  default_k: 5
```

Resolution order: CLI `--data-dir` → env `SKILL_MCP_DATA_DIR` → config.yaml → default `~/.skill-mcp`

Config is saved by `build-index` (records which backend/model was used). Never overwritten by `pull`.

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
pytest tests/ -v    # 132 tests, ~0.7s
```

Tests use `--backend mock` (deterministic hash-based 128-dim embeddings, no model download).

| Category | Tests | Coverage |
|----------|-------|----------|
| E2E workflow | 15 | init → import → build → search full lifecycle |
| Cross-feature | 9 | pull+import+build, incremental, dedup+rebuild |
| Server handlers | 11 | null store, invalid IDs, special chars, k=0 |
| Tool descriptions | 6 | behavioral triggers, workflow references, use-case context |
| Store | 14 | merge priority, empty source, FTS sync, batch |
| Index | 12 | incremental, deletion detection, save/load |
| Pull | 8 | merge, replace, dedup, fast path, stale index |
| Retriever | 5 | stale index, k > total, metadata |
| Schema/Config/FTS | 12 | partial YAML, roundtrip, special chars |
| Importers/Dedup/Embedding | 14 | nested dirs, source compat, mock backend |
| Data-dir/CLI | 10 | global override, envvar, nonexistent path |
| Source compat | 2 | SKILLNET store + dedup priority |

## MCP Server Instructions

The server passes an `instructions` string during MCP initialization. This tells the agent what the knowledge base contains and how tools relate to each other (search → get_skill workflow), so the agent can decide when to search based on the task — no extra configuration or agent-specific instruction files needed.

This is set via `Server(name, instructions=...)` in `server.py`. The instructions emphasize the **breadth** of the knowledge base (virtually every technical domain) and the **low cost** of searching (< 5ms, zero API calls) to encourage agents to search proactively. The design principle: rather than listing specific trigger scenarios (which limits when agents search), communicate that skills exist for nearly any task and searching is essentially free.

## MCP Tool Interface

### Two-step retrieval: search → filter → fetch

The core design is a **summary-first pipeline** that saves context tokens:

1. **Search** (`search_skills` or `keyword_search`) returns summaries — name, description, score, tags — but **no instructions**
2. **Agent reads summaries** and decides which skills are relevant based on descriptions and scores
3. **Fetch** (`get_skill`) retrieves full instructions only for the skills the agent actually needs

This means: 5 results searched, 1–2 skills fetched → 60–80% token savings compared to loading all results.

### search_skills

```json
{"query": "debug memory leak", "k": 5}
→ [
    {"id": "a1b2", "name": "debug-memory-leak", "description": "Identify and fix...", "score": 0.81, "category": "debugging", "tags": [...]},
    {"id": "c3d4", "name": "python-profiling", "description": "Profile Python...", "score": 0.72, ...},
    ...
  ]
```

Semantic search via FAISS. Agent reviews the returned descriptions and scores, then calls `get_skill` only for the most relevant results. Tool description emphasizes domain breadth and low search cost (< 5ms) to encourage agents to search proactively for any task.

### get_skill

```json
{"skill_id": "a1b2"}
→ {"id": "a1b2", "name": "debug-memory-leak", "instructions": "## Step 1: ...(full guide)...", ...}
```

Fetch full instructions. This is the only way to get the `instructions` field — search results deliberately omit it. Tool description references the search → get_skill workflow.

### keyword_search

```json
{"query": "docker deploy", "limit": 10}
→ [{"id": "...", "name": "...", "description": "...", ...}]
```

FTS5 text search. Same summary-only output as `search_skills`. Works without vector index. Special characters auto-escaped. Tool description steers agents to prefer this when they have specific tool names, error messages, or CLI commands.

### list_categories

```json
{}
→ [{"category": "debugging", "count": 42}, ...]
```

Browse available domains. Useful for discovery and scoping searches.

## Dependencies

Core: `mcp`, `faiss-cpu`, `numpy`, `click`, `pyyaml`, `tqdm`

Optional:
- `[local]` — `sentence-transformers` (default embedding backend)
- `[openai]` — `openai`, `tiktoken`
- `[ollama]` — `httpx`
- `[hf]` — `huggingface-hub` (for `pull`)
- `[sse]` — `starlette`, `uvicorn` (SSE transport)
- `[all]` — all optional deps
- `[dev]` — `pytest`, `pytest-asyncio`, `ruff`
