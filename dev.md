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
with a server that could not start, and it is now closed by the `e2e-stdio` job
described below.

### The `e2e-stdio` CI job

`tests/e2e/stdio_smoke.py`, run against a wheel installed into a fresh virtualenv,
is the only thing in CI that touches what users actually receive. It builds a
store and a FAISS index from the six-skill corpus in `tests/e2e/corpus/` using a
real sentence-transformers model, launches the venv's own `skill-mcp` console
script as a subprocess, and speaks the real stdio protocol to it.

Each of its shortcuts was removed for a reason:

- **the installed console script, not `python -m skill_mcp.cli`** — the entry
  point is generated at install time, so it only exists in the built artifact,
  and it is what every registration snippet tells an agent to run;
- **a real embedding model, not the mock backend** — the mcp 1.x failure happens
  at model load and is invisible to anything that never loads one;
- **two search queries with different right answers** — one query cannot tell a
  working ranker apart from a server returning a fixed order;
- **the tool result's error flag is checked** — MCP reports a server-side tool
  failure as an ordinary response carrying a flag, so a caller that only reads
  `.content` sees a plausible string and calls it a pass;
- **server stderr is captured and dumped on failure** — a server that dies during
  model load leaves the client holding nothing but `Connection closed`.

It was verified to actually fail: installing the same wheel with `mcp==1.14.0`
makes the job exit non-zero and print the server's own traceback.

Two things it deliberately does not cover. It runs on Python 3.10 only, the
declared floor, since the unit matrix already covers 3.11 and 3.12 for import
compatibility. And it builds its own corpus rather than pulling from HuggingFace,
so it proves the code path but not the published dataset.

The job takes about 75 seconds, so the cost of keeping it is small.

### The Windows leg of the unit matrix

The unit matrix also runs `windows-latest` on 3.10. Registration writes config
for editors and desktop apps, and two of the defects it shipped were
Windows-only: a resolved command path written into TOML opened a unicode escape
(`C:\Users` → `\U`), and a resolved drive root escaped the closing quote of a
printed command. Both fixes live behind `os.name == "nt"`, which a Linux-only
matrix cannot execute at all — and green on the maintainer's Windows box proves
as little about Linux as green on Linux proves about Windows. It is paired with
the oldest interpreter because nothing else covers that combination.

Two things about it are not obvious and cost three red runs to learn.

The first is that **the pip inside a fresh 3.10 virtualenv is 23.0.1**, which
discards any wheel whose metadata spells its own name differently from the
request — `Jinja2` for `jinja2`, `typing_extensions` for `typing-extensions` —
then falls back to the sdist and dies installing its build dependencies. Torch's
dependency closure trips this every time. The step upgrades pip before installing
anything, and a source build should be read as this bug returning, not as a
missing wheel.

The second is that **Actions run logs require admin credentials over the REST
API**, so the first red run was completely unreadable from a script. Annotations
are not privileged, so the `Surface the install failure` step folds the tail of
each pip log into one `::error::` annotation. That is the only reason the pip
version above was ever identified; it is diagnostic scaffolding kept on purpose.

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

`Skill.to_embedding_text()` is `name + description + instructions[:500]`. `all-MiniLM-L6-v2` accepts 256 word-pieces and silently drops the rest, so 63 of the 374 rows overflow — median 49 word-pieces discarded, worst case 227, and for a handful the cut lands inside the *description* rather than the instructions slice.

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

`tests/eval/embedding_recipe_sweep.py` reproduces the second and third tables, and is what keeps the `[:500]` comment in `schema.py` from being an unverifiable claim. It refuses to run if `recipe()` has drifted from `to_embedding_text()`, because a baseline arm that is no longer the shipped recipe makes every row below it meaningless. The first and last tables came from one-off ablations that were not kept — the bge rows there are run *without* the query prefix, so they are not the same arms as the sweep's.

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
refuses and an unsafe load would execute. `init` prints the patch instead.

Two upstream details are load-bearing and were read out of their parsers, not
their docs:

- Hermes declares `--args` as `argparse.REMAINDER`, so it swallows everything
  after it and must come last. Getting that wrong is **silent**: the run above
  parses `--command` as `None` and reports no error. It also has **no
  non-interactive flag**, and it exits 0 on every outcome. The prompt on our
  path is a bare `input()` whose EOF branch prints `Cancelled.` and saves
  nothing, while its other prompts go through a helper that returns *its
  default* on EOF — and one of those defaults is yes. So the exit code cannot
  distinguish a write from a no-op in either direction, and `_register_hermes`
  reads `config.yaml` back instead. Reading is safe; only writing destroys
  comments.
- OpenClaw takes `--arg`/`--env`/`--header` as repeated flags, not lists. It is
  `createOnly`, so re-running against an existing entry fails rather than
  overwriting, and it connects to the server to probe it before saving unless
  given `--no-probe`.

#### What the real parsers said

The three agents cannot be installed here — PyPI and npm are both blocked on
this network — so "verified" was raised from *read* to *executed*: upstream was
cloned over SSH and our exact argv run through their real code. Anchors:
`NousResearch/hermes-agent` @ `ec5e369f`, `openclaw/openclaw` @ `1bca8251`,
`deepseek-ai/deepseek-harness` @ `b150a551`, `tj/commander.js` @ `v15.0.0`.

That confirmed the `--arg`-per-argument and `--args`-must-be-last claims above,
and corrected or found three things:

- **Hermes can save a server disabled.** When its probe fails and the user
  saves anyway, it writes the entry with `enabled: false`, and its agent then
  filters disabled servers out of what the model sees. A read-back that only
  asked *is the key present* answered yes — a false positive in the exact
  mechanism that exists to prevent false positives. `_hermes_server_state` now
  answers `enabled` / `disabled` / `missing`, and the disabled case prints what
  to re-run.
- **OpenClaw probes before it saves**, and `init` offers registration *before*
  anything has been imported. That ordering only works because startup degrades
  on a missing index instead of failing, which is now pinned by
  `test_startup_survives_the_state_init_leaves_behind` rather than left to luck.
  Measured handshake on the 374-skill corpus is 1.4s against OpenClaw's 5s
  probe budget, and 1.1s with no index at all; the margin exists because the
  embedding model loads lazily on first search, not at startup.
- **The DeepSeek snippet did not register anything.** A `cordis.patch.yml` is a
  list of *operations*, not of rows. An operation carrying an `id` and no
  `insert` means "override the row that already has this id", so the bare row
  we used to print resolved to a patch against an id nothing defines —
  `applyEntryPatches` answers that with one stderr warning and continues. The
  snippet now emits the `insert:` wrapper, and the test parses it back and asks
  which operation it is rather than matching the text.

What still cannot be verified: that any of these three actually loads our tools
once registered. `tests/test_registration.py` uses a faked `subprocess.run`, so
it pins our side of the contract — that we hand OpenClaw its own arguments
rather than rewriting its commented config, that a Hermes no-op or disabled
entry is never reported as a registration, and that the DeepSeek snippet is an
insert — but the binaries have never run here.

#### The four configs we write ourselves

Delegating to `mcp add` is what protects OpenClaw and Hermes. The four files
`init` edits directly had no such protection, and putting the real shapes
through them turned up the same class of defect several more times.

- **The command has to be a path, not a name.** Every route used to write
  `command: "skill-mcp"`, which the *agent* resolves — and an editor or desktop
  app is launched from a session whose PATH routinely has never seen the venv or
  pipx directory the user installed into. The failure is an ENOENT on a name
  they never typed, and it is the most common reason an MCP server simply never
  appears. `_try_register_mcp` resolves it once with `shutil.which` and passes
  the result to all seven. A resolved path can go stale if that install moves,
  but the error then names the path that went away; when `which` finds nothing
  we say so rather than writing a guess in silence.
- **The data directory has to be spelled out for the same reason, and it matters
  more.** The argv was a bare `serve`, so `init --data-dir` prepared one
  directory and every agent opened another: `~` is re-resolved in whatever
  environment the agent spawns us from, and the config recording the choice is
  written *inside* the chosen directory, so nothing recovers it. Unlike a missing
  command this produces no error at all — the server starts, the agent lists its
  tools, and every search comes back empty. `init` now resolves the directory and
  the argv carries `--data-dir <path>` ahead of the subcommand. All four foreign
  parsers were re-checked against that shape rather than assumed: Hermes'
  `argparse.REMAINDER` and OpenClaw's repeated `--arg` both keep a value that
  starts with `--`, and Codex's `RawMcpServerConfig` takes `command` + `args`
  with everything else optional.
- **The next steps `init` prints are part of the product.** They named plain
  `skill-mcp pull` / `import` / `build-index`, so a user who chose a directory
  and pasted them filled the default one instead — success on every line, and a
  server that finds nothing. They now carry the same `--data-dir` when it is not
  the default, quoted so that pasting it runs the command that was shown: a
  resolved directory can end in a backslash (`init --data-dir D:\`), which
  escapes the closing quote and swallows the subcommand into the value. Windows
  gets forward slashes and unconditional quotes — a double quote cannot appear
  in a Windows path — and POSIX gets `shlex.quote`. Checked by parsing the
  printed line with `CommandLineToArgvW` and `shlex`, not by looking for the
  path inside it. A directory whose name *expands* is out of scope and has no
  fix on Windows: cmd substitutes `%X%` inside double quotes, PowerShell and Git
  bash substitute `$X`, a backtick starts a substitution in bash and an escape
  in PowerShell, and cmd understands no quote but the double one.
- **`config.yaml` has to record a directory that survives a change of cwd.** It
  stored `--data-dir` exactly as typed, so `init --data-dir ./data` wrote
  `data_dir: ./data` into a file that is read from wherever the agent or the
  user is later — the same silent miss the argv was just fixed for, left open
  for anyone who types a relative path. A relative path is now resolved before
  it is recorded; `~` is kept as typed, because re-resolving it per machine is
  the point on a synced dotfile.
- **A config we cannot parse has to be left alone.** `_register_mcp_json` is
  shared by Claude Code, Gemini CLI and Cursor, so it meets whatever three tools
  and their users left on disk. An empty file, a trailing comma, a non-object
  root, an `mcpServers` that is a list — each of those raised out of
  `_register_mcp_json` and took all of `skill-mcp init` with it. Comments are
  the interesting case: Cursor and VS Code both accept them, so that file works
  fine for its owner and re-serialising it is the same harm we avoid for
  OpenClaw. It now prints the entry and leaves the file byte-identical.
- **Appending TOML cannot be decided by looking at the shape.**
  `_register_codex_toml` adds a `[mcp_servers.<name>]` table, which is valid
  only if nothing already claims that key in a form it cannot extend. It used to
  swallow a parse failure and append anyway, and its already-registered check
  ran `name in data.get("mcp_servers", {})` with no type test — so a **valid**
  Codex config saying `mcp_servers = []` or `mcp_servers = "disabled"` got a
  colliding table, we printed `Registered in`, and Codex could then load *none*
  of its config. Guarding on `isinstance(..., dict)` is not enough either: an
  inline table `mcp_servers = { other = {...} }` parses to a `dict` exactly like
  a standard table does, yet it is closed and no header may extend it. Nothing
  in the parsed value tells them apart, so the append is now decided by parsing
  the candidate file and keeping it only if it still loads.
- **TOML and YAML both eat backslashes.** Resolving the command to an absolute
  path turned a latent quoting bug live: `command = "C:\Users\..."` opens a
  unicode escape that never completes, so on Windows every Codex registration
  would have written an unloadable config. The DeepSeek snippet had the mirror
  of it — a single-quoted YAML scalar ends at the first apostrophe, which an
  account name like `O'Brien` puts straight into the path. `_quoted` emits a
  JSON literal, the grammar both languages read back unchanged.
- **The parser that reads that TOML is not on every interpreter we support.**
  `tomllib` became stdlib in 3.11 and the declared floor is 3.10, so the first
  change to actually exercise the Codex path turned it into an uncaught
  `ModuleNotFoundError` that aborted all of `init` — the same failure the rest of
  this section is about, arriving through packaging instead of through a config
  file. `tomli` is now a dependency below 3.11 so the behaviour is identical
  everywhere, and a missing parser still ends in the printed snippet rather than
  a traceback. Local runs cannot see this: on 3.12 the fallback branch is dead
  code, and only the `test (3.10)` leg of CI reaches it.

### There is one data directory, and every command we print names it

The `init` bullet above fixed the commands `init` prints. The same defect was
everywhere else: `import`, `build-index`, `search`, `status` and `pull` all end
by telling the user what to run next, the MCP server hands the agent repair
commands for a human to paste, and `hub.py` raised an exception whose text was
one. Twelve sites in the CLI, four in the server and one in the hub named a
bare `skill-mcp`, so a user who chose a directory repaired the default one and
was told it worked.

`scope_flag` now lives in `config.py` — the leaf both `cli.py` and `server.py`
already import — and every one of those sites goes through it. The server takes
its copy from `configure_hints(config)` at startup, because the agent passed
`--data-dir` on a command line the human reading the answer never saw.
`hub.download_index` no longer prints a command at all: it raises the fact, and
`_pull_index`, which is the caller that knows the directory, supplies the
command.

`tests/test_printed_commands.py` does not name any of those strings. It scans
whatever a command actually printed for `skill-mcp ...`, splits each hit with
the real argv parser for the platform, and asserts `--data-dir` is present and
points at the directory under test — so a message added later is covered
without being listed. The fixture is parametrised over `elsewhere`, `my data`
and `O'Brien`, the three shapes where a path stops surviving the round trip,
and it repoints `HOME`/`USERPROFILE` first: a command that dropped the flag
would otherwise write into the developer's real `~/.skill-mcp` and pass.

The argv splitter it uses is the platform's own, so the `CommandLineToArgvW`
branch runs on exactly one CI leg and nowhere else. That made it the natural
home for an import bug: it reached `_windows_argv` as `tests.test_registration`,
which resolves only when the repo root is on `sys.path`. `python -m pytest` puts
it there and the `pytest` console script CI runs does not, so the suite was
green locally on Windows and red on the one leg that could see it. Import test
helpers by module name — there is no `tests/__init__.py`, and the directory
pytest adds is `tests/` itself.

`pull --help`'s example block is deliberately left unscoped. It is static
reference text baked in at definition time, before any per-invocation
`--data-dir` exists, and it never executes.

#### `--db` and `--output` are gone

`import`, `build-index` and `dedup` took a `--db`, and `build-index` also took
an `--output`. Nothing documented them, no test covered them, and they could
name a database and an index that were built from different stores. That
mistake is invisible: `retrieve` skips ids it cannot look up, so a cross-wired
pair returns nothing at exit 0, and only `status` — which compares the two
counts — says anything at all. All four are deleted; the paths come from
`--data-dir` alone. `test_every_indexed_id_resolves_in_the_store_it_was_built_from`
pins the invariant, and strands an index entry first so the repair it asserts
is measured against a real violation.

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
pytest tests/ -v    # 240 tests, ~6s
```

Tests use `--backend mock` (deterministic hash-based 128-dim embeddings, no model download).

| Category | Tests | Coverage |
|----------|-------|----------|
| E2E workflow | 16 | init → import → build → search full lifecycle |
| Cross-feature | 10 | pull+import+build, incremental, dedup+rebuild, store/index invariant |
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
| Printed commands | 31 | every `skill-mcp ...` we print carries `--data-dir`, parsed back with the platform's real argv splitter |

### The retrieval eval

`tests/eval/retrieval_eval.py` is not a pytest test and is not collected — it needs a built store, a real embedding model, and about a minute:

```bash
skill-mcp pull && skill-mcp build-index
python tests/eval/retrieval_eval.py            # or --data-dir /some/other/corpus
```

It runs 43 in-domain queries, each phrased the way an agent would phrase a task and never echoing the skill's own name, against a set of acceptable answers rather than one. On the shipped 374-skill corpus: **R@1 81.4%, R@3 90.7%, R@5 90.7%, MRR 0.853**. `@3 → @5` is zero gain — the 4th and 5th result never once supplied the answer, which is what the default `k=5` is actually buying. All 4 misses are vocabulary gaps between Google's branding and how a task gets described ("Agent Platform" vs "fine tune a foundation model", "SLO alerting policies" vs "error budget burns"), not gaps in the corpus.

The 15 out-of-domain queries are the more useful half. They name real work the corpus provably does not cover, and their top-1 scores are why **there is no score threshold anywhere in this codebase**: the best out-of-domain score (0.451) sits above the median in-domain score (0.428), so 25 of 43 real hits score at or below the best piece of noise. The threshold sweep the script prints has no working point. If a score cut-off is ever proposed again, run this first.

The numbers in *The embedding text overflows the model window* above came from this harness. Expected-answer sets are pinned to names in the published corpus, so a corpus change is supposed to move these numbers.

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
