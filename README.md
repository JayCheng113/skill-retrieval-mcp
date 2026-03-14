# skill-retrieval-mcp

> Your agent doesn't need 200K skills in context. It needs the right 5.

An MCP server that brings **RAG to skill loading**. Instead of pre-loading all skills into your agent's context, it retrieves only the most relevant ones per task — zero LLM calls, millisecond latency.

Works with **Claude Code**, **Codex CLI**, **Gemini CLI**, **Cursor**, and any MCP-compatible agent.

| | Pre-loading | skill-retrieval-mcp |
|---|---|---|
| **Scale** | 10–20 skills | 200K+ |
| **Selection** | Manual | Semantic similarity |
| **Latency** | — | < 5ms |
| **Context cost** | All loaded | Top-k only |

## Quick Start

```bash
# 1. Install
pip install "skill-retrieval-mcp[local,hf]"

# 2. Download 89K skills + pre-built vector index
skill-mcp pull --include-index

# 3. Register with your agent
skill-mcp init                   # interactive — auto-detects Claude Code, Cursor
```

Or register manually:

```json
{"mcpServers": {"skill-retrieval": {"command": "skill-mcp", "args": ["serve"]}}}
```

Done. Your agent now has 4 tools: `search_skills`, `get_skill`, `keyword_search`, `list_categories`.

## How It Works

The agent calls **search → fetch** as needed:

```
Agent: search_skills({"query": "debug memory leak in python", "k": 3})
→ [{"id": "a1b2", "name": "debug-memory-leak", "score": 0.81, ...}, ...]

Agent: get_skill({"skill_id": "a1b2"})
→ {"instructions": "Memory leaks cause applications to consume increasing RAM..."}
```

`search_skills` returns summaries only (no instructions) to save context tokens. The agent calls `get_skill` for the ones it actually needs.

| Tool | What it does |
|------|-------------|
| `search_skills` | Semantic search — top-k skill summaries with scores |
| `get_skill` | Full instructions for a skill by ID |
| `keyword_search` | FTS5 text search — works without vector index |
| `list_categories` | Browse all skill categories and counts |

## Adding Your Own Skills

Create `SKILL.md` files anywhere:

```markdown
---
name: "debug-memory-leak"
description: "Identify and fix memory leaks in long-running applications"
tags: ["debugging", "memory", "profiling"]
---

Your detailed skill instructions here...
```

Import and index:

```bash
skill-mcp import --source directory --path ~/my-skills/
skill-mcp build-index             # incremental — only encodes new skills
```

This works alongside pre-built skills from `pull`. Deduplication is automatic (priority: ANTHROPIC > COMMUNITY > LANGSKILLS > SKILLNET).

## Embedding Backends

Default: `sentence-transformers/all-MiniLM-L6-v2` (384-dim, local, free).

| Backend | Install | Pre-built index | Requires |
|---------|---------|-----------------|----------|
| `sentence-transformers` | `pip install skill-retrieval-mcp[local]` | `--include-index` (137MB) | Nothing |
| `openai` | `pip install skill-retrieval-mcp[openai]` | `--include-index` (1.1GB) | `OPENAI_API_KEY` |
| `ollama` | `pip install skill-retrieval-mcp[ollama]` | build locally | Ollama running |

To switch backends:

```bash
skill-mcp build-index --backend openai --model text-embedding-3-large --force
```

One index = one embedding model. `build-index` detects model mismatches and requires `--force` to rebuild.

## Pull Options

`pull` merges by default — your custom skills are preserved.

```bash
skill-mcp pull                    # merge 89K skills into local store
skill-mcp pull --include-index    # also download pre-built vector index
skill-mcp pull --replace          # replace local DB entirely (discard custom skills)
```

Without `--include-index`, run `skill-mcp build-index` to build the vector index locally (~7 min on CPU).

## CLI Reference

```
skill-mcp init [--no-register]              Create data dir, config, register with agents
skill-mcp pull [--replace] [--include-index] Download/merge pre-built dataset from HuggingFace
skill-mcp import --source SOURCE --path PATH Import skills from directory/langskills/anthropic
skill-mcp build-index [--backend B] [--force] Build or incrementally update vector index
skill-mcp serve [--transport stdio|sse]      Start MCP server
skill-mcp search QUERY [--k N]              Test search locally
skill-mcp status                            Show skills/index/config status
skill-mcp dedup                             Remove duplicate skills
```

All commands support `--data-dir DIR` or env `SKILL_MCP_DATA_DIR` for custom locations.

## Development

```bash
git clone https://github.com/JayCheng113/skill-retrieval-mcp
cd skill-retrieval-mcp
pip install -e ".[all,dev]"
pytest tests/ -v
```

Architecture, data model, and extension guide: [`dev.md`](dev.md)

## License

MIT
