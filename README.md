# skill-retrieval-mcp

> Your agent doesn't need 200K skills in context. It needs the right 5.

An MCP server that retrieves relevant skills per task via semantic search — instead of loading them all into context. Zero LLM calls, millisecond latency.

Works with **Claude Code**, **Codex CLI**, **Gemini CLI**, **Cursor**, and any MCP-compatible agent.

| | Pre-loading all skills | skill-retrieval-mcp |
|---|---|---|
| **Scale** | 10–20 skills | 200K+ |
| **Selection** | Manual | Semantic similarity |
| **Latency** | — | < 5ms |
| **Context cost** | All loaded | Top-k only |

## Get Started

### 1. Install

```bash
pip install "skill-retrieval-mcp[local,hf]"
```

`[local]` installs `sentence-transformers` for query embedding. `[hf]` installs `huggingface-hub` for downloading skills.

### 2. Download skills and index

```bash
skill-mcp pull --include-index
```

This downloads two things from [HuggingFace](https://huggingface.co/datasets/zcheng256/skillretrieval-data):
- **89,267 skills** (960MB SQLite database) — sourced from LangSkills, SkillNet, Anthropic official, and community
- **Pre-built vector index** (137MB) — 384-dim vectors built with `all-MiniLM-L6-v2`, ready for search

No local computation needed. If you prefer to build the index yourself, omit `--include-index` and run `skill-mcp build-index` (~7 min on CPU).

### 3. Register with your agent

```bash
skill-mcp init    # auto-detects Claude Code and Cursor, prompts to register
```

Or add manually to your agent's MCP config:

```json
{"mcpServers": {"skill-retrieval": {"command": "skill-mcp", "args": ["serve"]}}}
```

That's it. Your agent now has access to 89K searchable skills.

## How Your Agent Uses It

The agent calls **search → fetch** as needed:

```
Agent: search_skills({"query": "debug memory leak in python", "k": 3})
→ [{"id": "a1b2", "name": "debug-memory-leak", "score": 0.81, ...}, ...]

Agent: get_skill({"skill_id": "a1b2"})
→ {"instructions": "Memory leaks cause applications to consume increasing RAM..."}
```

`search_skills` returns summaries only (no instructions) to save context tokens. The agent calls `get_skill` for the ones it needs.

| Tool | What it does |
|------|-------------|
| `search_skills` | Semantic search — top-k skill summaries with scores |
| `get_skill` | Full instructions for a skill by ID |
| `keyword_search` | FTS5 text search — works without vector index |
| `list_categories` | Browse all skill categories and counts |

## Add Your Own Skills

Create `SKILL.md` files:

```markdown
---
name: "debug-memory-leak"
description: "Identify and fix memory leaks in long-running applications"
tags: ["debugging", "memory", "profiling"]
---

Your detailed skill instructions here...
```

Import them:

```bash
skill-mcp import --source directory --path ~/my-skills/
skill-mcp build-index    # incremental — only encodes the new skills you just added
```

Your custom skills live alongside the pre-built ones. Deduplication is automatic (priority: ANTHROPIC > COMMUNITY > LANGSKILLS > SKILLNET).

## Choose an Embedding Backend

The default setup uses `sentence-transformers/all-MiniLM-L6-v2` — a local model (384-dim, free, no API key). This is what the pre-built index from `pull --include-index` uses, and what encodes your search queries at runtime.

You can switch to a different backend:

| Backend | Install | Pre-built index on HF | Requires |
|---------|---------|----------------------|----------|
| `sentence-transformers` (default) | `pip install skill-retrieval-mcp[local]` | 137MB | Nothing |
| `openai` | `pip install skill-retrieval-mcp[openai]` | 1.1GB | `OPENAI_API_KEY` |
| `ollama` | `pip install skill-retrieval-mcp[ollama]` | — (build locally) | Ollama running |

```bash
# Rebuild all vectors with a different model
skill-mcp build-index --backend openai --model text-embedding-3-large --force
```

One index = one embedding model. All vectors must come from the same model. `build-index` detects mismatches and requires `--force` to rebuild.

## Pull Options

```bash
skill-mcp pull                    # merge 89K skills into local store (preserves your custom skills)
skill-mcp pull --include-index    # also download pre-built vector index
skill-mcp pull --replace          # replace local DB entirely (discards custom skills)
```

`pull` merges by default. Running it again skips existing skills.

## CLI Reference

```
skill-mcp init [--no-register]               Create data dir, config, register with agents
skill-mcp pull [--replace] [--include-index]  Download/merge pre-built dataset from HuggingFace
skill-mcp import --source SOURCE --path PATH  Import skills from directory/langskills/anthropic
skill-mcp build-index [--backend B] [--force] Build or incrementally update vector index
skill-mcp serve [--transport stdio|sse]       Start MCP server
skill-mcp search QUERY [--k N]               Test search locally
skill-mcp status                              Show skills/index/config status
skill-mcp dedup                               Remove duplicate skills
```

All commands support `--data-dir DIR` or env `SKILL_MCP_DATA_DIR` for custom data locations.

## Development

```bash
git clone https://github.com/JayCheng113/skill-retrieval-mcp
cd skill-retrieval-mcp
pip install -e ".[all,dev]"
pytest tests/ -v
```

Architecture, design decisions, and extension guide: [`dev.md`](dev.md)

## License

MIT
