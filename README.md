# skill-retrieval-mcp

> Your agent doesn't need 200K skills in context. It needs the right 5.

A lightweight MCP Server that brings **RAG (Retrieval-Augmented Generation) to skill loading**. Instead of pre-loading all available skills into your AI agent's context window, `skill-retrieval-mcp` dynamically retrieves only the most relevant skills for the current task — with zero LLM calls and millisecond latency.

Works with any MCP-compatible agent: **Claude Code**, **Codex CLI**, **Gemini CLI**, **Cursor**, and more.

## Why?

Modern skill libraries contain **100K–250K+ skills** (LangSkills, SkillNet, Anthropic official, community). But agents can only keep **10–20 skills** in context at a time. Pre-loading is a dead end.

`skill-retrieval-mcp` solves this:

| | Pre-loading | skill-retrieval-mcp |
|---|---|---|
| **Scale** | 10–20 skills | 200K+ skills |
| **Selection** | Manual / static | Automatic by semantic relevance |
| **Latency** | N/A | < 5ms per query |
| **LLM calls** | 0 | 0 |
| **Context cost** | All skills always loaded | Only top-k relevant skills |

## Quick Start

```bash
# Install
pip install skill-retrieval-mcp

# Initialize (creates ~/.skill-mcp/, optional agent registration)
skill-mcp init

# Import skills from a directory of SKILL.md files
skill-mcp import --source directory --path ~/my-skills/

# Build the vector index
skill-mcp build-index --backend sentence-transformers

# Done — your agent can now use search_skills, get_skill, etc.
```

## How It Works

```
                    ┌──────────────────────┐
                    │   Your AI Agent      │
                    │ (Claude Code, etc.)  │
                    └──────────┬───────────┘
                               │ MCP Protocol
                    ┌──────────▼───────────┐
                    │   skill-mcp serve    │
                    │                      │
                    │  search_skills(query)│──→ FAISS vector search
                    │  get_skill(id)       │──→ SQLite lookup
                    │  keyword_search(q)   │──→ FTS5 text search
                    │  list_categories()   │──→ Category index
                    └──────────────────────┘
                         ▲            ▲
                    skills.db    index.faiss
                    (SQLite)      (FAISS)
```

**Offline/Online separation**: Import skills and build indices offline via CLI. The MCP server only does read-only queries at runtime — fast and stateless.

## MCP Tools

The server exposes 4 tools to your agent:

### `search_skills` — Semantic search (main tool)

Find the most relevant skills for a task by semantic similarity.

```json
{"query": "debug memory leak in python", "k": 5}
```

Returns summaries (not full instructions) to save context tokens:

```json
[
  {"id": "abc123", "name": "debug-memory-leak", "description": "Identify and fix memory leaks...", "score": 0.81, "category": "debugging", "tags": ["memory", "profiling"]},
  {"id": "def456", "name": "debug-python", "description": "Systematic debugging techniques...", "score": 0.50, ...}
]
```

### `get_skill` — Full skill content

Fetch the complete instructions for a specific skill (two-step pattern: search first, then fetch what you need):

```json
{"skill_id": "abc123"}
```

### `keyword_search` — FTS5 text search

Keyword-based search. Works even without a vector index built:

```json
{"query": "docker deploy", "limit": 10}
```

### `list_categories` — Browse categories

```json
→ [{"category": "debugging", "count": 12}, {"category": "testing", "count": 8}, ...]
```

## Retrieval Quality

With `all-MiniLM-L6-v2` (384-dim, local, free):

| Query | Top-1 Result | Score |
|-------|-------------|-------|
| "debug memory leak in python" | debug-memory-leak | 0.81 |
| "resolve git merge conflicts" | git-resolve-conflicts | 0.76 |
| "containerize my app with docker" | docker-containerize | 0.66 |
| "design a REST API" | rest-api-design | 0.59 |
| "write unit tests with pytest" | write-unit-tests | 0.45 |

## Skill Sources

Import skills from multiple sources at scale:

```bash
# Local SKILL.md directory (→ SkillSource.COMMUNITY)
skill-mcp import --source directory --path ~/my-skills/

# Anthropic official skills repo (→ SkillSource.ANTHROPIC)
skill-mcp import --source anthropic --path ~/anthropic-skills/

# LangSkills SQLite bundle (→ SkillSource.LANGSKILLS)
skill-mcp import --source langskills --path langskills.db

# SkillNet JSON-lines dump (→ SkillSource.SKILLNET)
skill-mcp import --source skillnet --path skillnet.jsonl
```

Cross-source deduplication is automatic. Priority: ANTHROPIC > COMMUNITY > LANGSKILLS > SKILLNET.

### SKILL.md Format

```markdown
---
name: "debug-memory-leak"
description: "Identify and fix memory leaks in long-running applications"
tags: ["debugging", "memory", "profiling"]
---

## Instructions

Your detailed skill instructions here...
```

## Embedding Backends

Configurable via `~/.skill-mcp/config.yaml` or CLI flags:

| Backend | Model | Dimensions | Requires |
|---------|-------|-----------|----------|
| `sentence-transformers` | all-MiniLM-L6-v2 | 384 | `pip install skill-retrieval-mcp[local]` |
| `openai` | text-embedding-3-large | 3072 | `pip install skill-retrieval-mcp[openai]` + API key |
| `ollama` | nomic-embed-text | 768 | `pip install skill-retrieval-mcp[ollama]` + Ollama running |

```bash
# Build with local model (free, offline)
skill-mcp build-index --backend sentence-transformers --model all-MiniLM-L6-v2

# Build with OpenAI (highest quality)
skill-mcp build-index --backend openai --model text-embedding-3-large

# Rebuild with different backend
skill-mcp build-index --backend ollama --model nomic-embed-text --force
```

## CLI Reference

```
skill-mcp init [--data-dir DIR] [--no-register]   Initialize data directory and config
skill-mcp import --source SOURCE --path PATH       Import skills into the store
skill-mcp build-index [--backend B] [--model M]    Build FAISS vector index
skill-mcp serve [--transport stdio|sse]            Start MCP server
skill-mcp search QUERY [--k N]                     Local search (for testing)
skill-mcp status                                   Show store/index/config status
skill-mcp dedup                                    Run cross-source deduplication
```

## Configuration

`~/.skill-mcp/config.yaml` (created by `skill-mcp init`, optional — defaults are used if missing):

```yaml
embedding:
  backend: sentence-transformers
  model: all-MiniLM-L6-v2

server:
  transport: stdio
  name: skill-retrieval

search:
  default_k: 5
```

## Agent Integration

### Claude Code

```bash
skill-mcp init  # select "yes" when prompted to register
```

Or manually add to `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "skill-retrieval": {
      "command": "skill-mcp",
      "args": ["serve"]
    }
  }
}
```

### Cursor

Add to `.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "skill-retrieval": {
      "command": "skill-mcp",
      "args": ["serve"]
    }
  }
}
```

### Any MCP-compatible Agent

The server uses stdio transport by default. Point your agent's MCP config to `skill-mcp serve`.

## Architecture

```
src/skill_mcp/
├── server.py          # MCP Server — 4 tool handlers
├── cli.py             # Click CLI — init/import/build-index/serve/status/search
├── config.py          # YAML config loading with defaults
├── store.py           # SQLite + FTS5 skill storage
├── schema.py          # Skill/RetrievedSkill data models
├── index.py           # FAISS vector index (build/search/save/load)
├── embeddings.py      # Multi-backend embeddings (OpenAI/ST/Ollama/mock)
├── retriever.py       # Vector similarity retrieval
├── dedup.py           # Content-hash deduplication with source priority
└── importers/         # Pluggable importers (directory/langskills/skillnet/anthropic)
```

~15 source files total. No agent framework, no evaluation infrastructure, no experiment runners — just skill storage, indexing, and serving.

## Scalability

| Metric | Value |
|--------|-------|
| Max skills | 200K+ tested |
| Index memory | ~300MB (384-dim × 200K) |
| Search latency | < 5ms |
| SQLite on disk | ~500MB for 200K skills |
| Query embedding | ~10ms (local) / ~100ms (API) |

## Dependencies

**Core (6 packages)**:
`mcp`, `faiss-cpu`, `numpy`, `click`, `pyyaml`, `tqdm`

**Optional**: `sentence-transformers`, `openai`, `httpx` (for Ollama)

## Development

```bash
git clone https://github.com/your-org/skill-retrieval-mcp
cd skill-retrieval-mcp
pip install -e ".[all,dev]"
pytest tests/ -v
```

## License

MIT
