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

~1950 lines across 17 source files.

## mcp Version Support

The declared floor is `mcp>=2.0`, which is narrower than it looks: mcp 1.x also
*imports* and *serves*, but semantic search kills the process there.

The high-level server API ships under two names — `FastMCP` on mcp 1.x,
`MCPServer` on 2.x — with an identical `.tool()` signature, so `server.py`
carried a two-line try/except shim and declared `mcp>=1.14` (1.13 and earlier
crash in `Tool.from_function` on `Annotated[...]` parameters: they call
`issubclass()` on an annotation that is not a class). That floor was never true.
Measured in one venv, one corpus, one model, changing only the mcp version:

| | mcp 2.0 | mcp 1.14 |
|---|---|---|
| handshake, `list_tools` | pass | pass |
| `keyword_search` over stdio | pass, 0.9ms | pass, 0.9ms |
| `skill-mcp search` (loads the model, no MCP) | pass | pass, identical scores |
| `search_skills` over stdio | pass, 0.664 | **server dies**, client sees `Connection closed` |

So the model is fine and the server is fine; the one path that dies is *loading
the embedding model inside an mcp 1.x stdio server* — which is the reason this
product exists. The death is silent: no traceback on the server's stderr, and
the startup warm-up never logs `embedding: loaded` even after 45s idle.
Removing the background warm entirely does not fix it. **The root cause was
never found, only isolated**, which is why the floor moved rather than a
workaround landing.

CI used to run a `test-mcp-floor` leg pinned to `mcp==1.14.0` and it was green
the whole time, because the suite uses the mock embedding backend and dispatches
in-process — it never spawns a subprocess and never loads a real model. That leg
is gone along with the shim. The gap it left is the same one that let 0.2.0 ship
with a server that could not start: **nothing in CI exercises the built
artifact end-to-end over real stdio.** Until something does, run
`skill-mcp serve` from a clean install of the wheel before tagging a release.

## Module Responsibilities

| Module | Lines | Role |
|--------|-------|------|
| `cli.py` | 542 | CLI commands, orchestration, no business logic |
| `server.py` | 288 | MCP protocol handlers, server instructions, structured logging, read-only runtime |
| `store.py` | 250 | SQLite CRUD + FTS5, dedup-on-insert, batch commit, merge |
| `index.py` | 139 | FAISS build/update/search/save/load |
| `embeddings.py` | 112 | Backend abstraction (ST, OpenAI, Ollama, mock) |
| `config.py` | 109 | YAML config with computed paths |
| `schema.py` | 89 | `Skill` dataclass, deterministic ID/hash |
| `hub.py` | 60 | HuggingFace download (DB + index by backend/model) |
| `retriever.py` | 37 | query → embed → FAISS search → store lookup |
| `dedup.py` | 28 | Source-priority dedup by content_hash |
| `importers/` | ~300 | Curated, Directory, Anthropic parsers + shared frontmatter |

## Data Model

### Skill

```
id            = sha256(f"{source}:{name}:{content_hash[:8]}")[:16]
content_hash  = md5(instructions)
```

- `id` is deterministic: same source + name + content → same ID
- `content_hash` drives dedup: same instructions = same hash regardless of source/name
- `to_embedding_text()` = `name\ndescription\ninstructions[:500]` — the slice is a measured optimum, not a size limit; see the embedding-window section below

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
├── processed/skills.db                                    6.4MB
└── indices/sentence-transformers/all-MiniLM-L6-v2/               (384-dim)
    ├── index.faiss
    └── skill_ids.json
```

Only the default backend has a published index. An index is a list of `skill_ids` in FAISS row order, so it is valid only for the exact corpus that built it — `retrieve()` drops IDs the store doesn't have, which turns a mismatched index into silently empty results rather than an error. Publishing an index for a corpus we no longer ship would be worse than publishing none.

`pull --include-index` downloads the index matching `config.embedding.backend/model`. `download_index()` in `hub.py` constructs the path as `indices/{backend}/{model}/`.

## Key Design Decisions

### Dedup happens at insert time, not as a batch

`_add_skill_detail` checks `content_hash` before every insert. If a match exists, source priority decides:

```
ANTHROPIC(4) > COMMUNITY(3) > LANGSKILLS(2) > SKILLNET(1)
```

Higher priority replaces lower. Equal or lower is silently skipped. The `dedup` CLI command only catches duplicates injected via raw SQL (bypassing `_add_skill_detail`).

`LANGSKILLS` and `SKILLNET` no longer have importers. The enum values stay so an older `skills.db` still deserializes instead of raising on read.

### Curated import: an unvetted repo aborts the whole run

`CuratedImporter` keys every on-disk `<owner>/<repo>` directory against `CURATED_REPOS`, a manifest of repositories whose licence was checked by hand. A directory with no manifest entry raises `UnvettedRepositoryError` and nothing is written — skipping it silently would let unlicensed content reach the corpus on the next careless clone, and the corpus is redistributed.

Every imported row therefore carries `metadata["license"]`, `repo`, `repo_url` and `url`. When a skill declares its own narrower licence in frontmatter (K-Dense ships BSD-3-Clause files under an MIT repo), it is kept verbatim as `declared_license` beside the repo licence rather than reconciled.

None of the eight repos use frontmatter `tags`, so `tags` is empty for all 374 curated rows. It stays in the schema because directory imports of your own skills do populate it.

### Commit strategy: batch, not per-row

`_add_skill_detail` does NOT commit. Public methods (`add_skill`, `add_skills`, `merge_from`) commit once after all mutations — one fsync per batch instead of one per row.

### Auto-index after import

`import` automatically calls `_auto_index()` after importing new skills:
- **Index exists** → incremental update (only encode new skills)
- **No index yet** → prompt user to run `build-index` (avoids loading heavy embedding model unexpectedly)
- **Embedding mismatch** → skip and prompt for `build-index --force`

Skip with `--no-index` for batch imports (import from multiple sources, then build once).

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

### The embedding text overflows the model window, and that turns out not to matter

`Skill.to_embedding_text()` is `name + description + instructions[:500]`. `all-MiniLM-L6-v2` accepts 256 word-pieces and silently drops the rest, so about 16% of rows overflow — median 47 word-pieces discarded, worst case 227, and for a handful the cut lands inside the *description* rather than the instructions slice.

That is a fact about the input. It was assumed to be a fact about the output too, and it is not. Three measurements on the 43-query eval set, all with the shipped retrieval path (normalized vectors, inner product) reproduced in numpy — the control row below matches the shipped numbers to the digit, so the instrument is the same one:

**Removing the overflow entirely changes nothing.** `BAAI/bge-small-en-v1.5` is 384-dimensional like MiniLM but takes 512 word-pieces, so the same corpus can be embedded with the window as the only moving part:

| model | window | rows overflowing | R@1 | R@3 | R@5 | MRR |
| --- | --- | --- | --- | --- | --- | --- |
| bge-small | 256 | 62 | 67.4% | 79.1% | 86.0% | 0.736 |
| bge-small | 512 | **0** | 67.4% | 79.1% | 86.0% | 0.732 |

Sixty-two rows got their discarded tail back and not one of the 43 queries changed bucket.

**The window is an absolute ceiling, so the discarded tail is unreachable rather than wasted.** Widening the recipe slice on the shipped model does not move a single number, because everything added lands outside the window:

| recipe (MiniLM @256) | median embedding text | worst-case discard | R@1 | R@3 | R@5 | MRR |
| --- | --- | --- | --- | --- | --- | --- |
| `instructions[:500]` | 841 ch | 227 wp | 81.4% | 90.7% | 90.7% | 0.853 |
| `instructions[:1000]` | 1340 ch | 354 wp | 79.1% | 88.4% | 93.0% | 0.839 |
| `instructions[:2000]` | 2340 ch | 635 wp | 79.1% | 88.4% | 93.0% | 0.839 |
| `instructions` in full | 10138 ch | 21890 wp | 79.1% | 88.4% | 93.0% | 0.839 |

The last three rows are identical while the discarded tail grows sixty-fold. `[:500]` is therefore not an arbitrary number — it is the best of the tried slices on R@1/R@3/MRR, and the only one that also happens to keep most rows inside the window.

**Actually fixing the overflow makes retrieval worse.** A 512-window model with zero overflowing rows, given the query prefix its model card asks for, still loses to the truncating one — and its score separation is worse, with the best out-of-domain query outranking the median in-domain query:

| config | R@1 | R@3 | in-domain median | out-of-domain max |
| --- | --- | --- | --- | --- |
| MiniLM @256, `[:500]` (ships) | 81.4% | 90.7% | 0.428 | 0.451 |
| bge-small @512, `[:500]` | 67.4% | 79.1% | 0.699 | 0.730 |
| bge-small @512, `[:2000]` | 76.7% | 86.0% | 0.716 | 0.740 |

What *is* load-bearing is including instructions at all — dropping the slice costs 9 points of R@1 and pushes out-of-domain scores up:

| recipe (MiniLM @256) | R@1 | R@3 | MRR | out-of-domain top-1 (max / median) |
| --- | --- | --- | --- | --- |
| `name + description + instructions[:500]` | 81.4% | 90.7% | 0.853 | 0.451 / 0.284 |
| `name + description` | 72.1% | 83.7% | 0.780 | 0.473 / 0.336 |

So: the overflow is closed as measured-and-rejected, not deferred. Two caveats on the evidence. The eval set is 43 in-domain queries, where one query is 2.3% of recall, so anything under about 5 points is noise — the window result survives that only because all three recall buckets came out exactly equal, not merely close. And only two small encoders were compared; a genuinely stronger long-window model (gte-base, nomic, ~137M parameters and roughly six times the download) might beat MiniLM, but that would be buying a better model rather than fixing the truncation, and it trades directly against keeping this package small.

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

### Agent registration: write the file, or call their CLI

`_try_register_mcp` covers seven agents by three different routes, and the
split is deliberate.

Claude Code, Gemini CLI, Cursor and Codex each keep MCP servers in a small
dedicated file (`.mcp.json`, `settings.json`, `mcp.json`, `config.toml`), so
`init` edits those directly. OpenClaw and Hermes do not: OpenClaw's
`~/.openclaw/openclaw.json` is documented with **JSON5** examples, so a user's
real file can contain comments that `json.load` refuses and `json.dump` would
erase, and Hermes' `<hermes_home>/config.yaml` is a whole hand-written main
config that a pyyaml round-trip would reflow. Both ship their own `mcp add`,
so we shell out and never parse their file. DeepSeek Harness gets neither: its
entire command surface is `--profile`/`--patch`/`--dump-config` plus `web` and
`plugin`, registration is a Cordis patch overlay whose format is an explicit
developer preview, and its shipped examples carry `!!js` tags that `safe_load`
refuses and an unsafe load would execute. `init` prints the row instead.

Two upstream details are load-bearing and were read out of their parsers, not
their docs:

- Hermes declares `--args` as `argparse.REMAINDER`, so it swallows everything
  after it and must come last. More importantly it has **no non-interactive
  flag**: it prompts with a bare `input()` after probing, and on EOF or a
  declined prompt it prints `Cancelled.` and **exits 0 without saving**. Its
  exit code therefore cannot distinguish a write from a no-op, so
  `_register_hermes` reads `config.yaml` back and only claims success if the
  key is actually there. Reading is safe; only writing destroys comments.
- OpenClaw takes `--arg`/`--env`/`--header` as repeated flags, not lists. It is
  `createOnly`, so re-running against an existing entry fails rather than
  overwriting, and it connects to the server to probe it before saving unless
  given `--no-probe`.

Caveat worth keeping in view: **none of these three is installed on any machine
this has been developed on**, so the delegation is verified against upstream
source and unit tests with a faked `subprocess.run`, never against the real
binaries. `tests/test_registration.py` pins the part that would hurt most — that
we hand OpenClaw its own arguments rather than rewriting its commented config,
and that a Hermes no-op is never reported as a registration.

## Extension Points

### Adding a new embedding backend

1. Add branch in `EmbeddingModel.__init__` and `encode`
2. Add optional dependency in `pyproject.toml`

### Adding a new importer

1. Create `importers/myformat.py` implementing `BaseImporter` protocol
2. Use `split_frontmatter()` from `importers/frontmatter.py` if parsing SKILL.md
3. Add CLI branch in `import_skills` command + `click.Choice`

### Adding a new MCP tool

1. Add an `async def` decorated with `@server.tool(name=..., description=..., structured_output=False)` in `server.py`
2. Annotate each parameter with `Annotated[T, Field(description=...)]` — the input schema is derived from the signature
3. Add handler function `_handle_*` with `_store` null check, and route to it via `_dispatch`

Tools must stay `async`. mcp 2.x runs sync tool callables on a worker thread, and `SkillStore` holds a thread-bound SQLite connection.

### Adding a new skill source

1. Add variant to `SkillSource` enum in `schema.py`
2. Add priority in `dedup.py:_SOURCE_PRIORITY`

### Adding a repository to the curated corpus

1. Read its LICENSE and confirm it permits redistribution
2. Add a `CuratedRepo(slug, spdx, source)` entry to `CURATED_REPOS` in `importers/curated.py`
3. Clone it to `<root>/<owner>/<repo>` and re-run `import --source curated`

Step 1 is the hard gate, and step 3 should be measured before it is committed: stage the candidate beside the existing corpus, embed both, and check whether the new rows actually win any query. A repo that never enters a top-3 is weight without reach.

#### Evaluated and not added

`multica-ai/andrej-karpathy-skills` — rejected on both counts, so it does not need re-researching.

- **Licence.** The repository has no LICENSE file (GitHub reports `license: None`). The only MIT claim is a `license: MIT` line in the frontmatter of its single 2.5KB SKILL.md, and the repo's own description says the content is "derived from Andrej Karpathy's observations". A frontmatter string is not a grant from the copyright holder, and this corpus is redistributed.
- **Reach.** Staged and embedded anyway to check: across 12 queries — including "refactor this function to be simpler", the query it should own — adding it moved no ranking and it entered no top-3.

Popularity is not evidence of fit: this repo has >200k stars. Its content is a CLAUDE.md-style behavioural guideline, not the procedural how-to that `search_skills` is built to surface.

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
pytest tests/ -v    # 143 tests, ~0.7s
```

Tests use `--backend mock` (deterministic hash-based 128-dim embeddings, no model download).

| Category | Tests | Coverage |
|----------|-------|----------|
| E2E workflow | 16 | init → import → build → search full lifecycle |
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
| Auto-index | 6 | incremental, no-index, mismatch, no-existing-index, multiple imports |
| Source compat | 2 | SKILLNET store + dedup priority |
| Curated importer | 3 | unvetted repo aborts, licence+URL on every row, category |

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

Core: `mcp`, `pydantic`, `faiss-cpu`, `numpy`, `click`, `pyyaml`, `tqdm`

Optional:
- `[local]` — `sentence-transformers` (default embedding backend)
- `[openai]` — `openai`, `tiktoken`
- `[ollama]` — `httpx`
- `[hf]` — `huggingface-hub` (for `pull`)
- `[sse]` — `starlette`, `uvicorn` (SSE transport)
- `[all]` — all optional deps
- `[dev]` — `pytest`, `pytest-asyncio`, `ruff`
