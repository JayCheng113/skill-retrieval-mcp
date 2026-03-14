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

**2 commands to go from zero to 89K searchable skills:**

```bash
pip install "skill-retrieval-mcp[local,hf]"
skill-mcp pull --include-index    # download 89K skills + pre-built vector index
```

That's it. Register with your agent and start using:

```bash
# Claude Code — auto-registers during init
skill-mcp init

# Or add manually to ~/.claude/settings.json
```

```json
{"mcpServers": {"skill-retrieval": {"command": "skill-mcp", "args": ["serve"]}}}
```

> `--include-index` downloads a pre-built vector index so you skip the local embedding step entirely. Without it, run `skill-mcp build-index` to build locally (~7 min on CPU).

## How Your Agent Uses It

The server exposes 4 tools. The typical flow is **search → fetch**:

```
Agent: search_skills({"query": "debug memory leak in python", "k": 3})
→ [{"id": "a1b2", "name": "debug-memory-leak", "score": 0.81, ...}, ...]

Agent: get_skill({"skill_id": "a1b2"})
→ {"instructions": "Memory leaks cause applications to consume increasing RAM..."}
```

| Tool | What it does |
|------|-------------|
| `search_skills` | Semantic search — returns top-k skill summaries with scores |
| `get_skill` | Fetch full instructions for a skill by ID |
| `keyword_search` | FTS5 text search — works without vector index |
| `list_categories` | Browse all skill categories and counts |

`search_skills` returns summaries only (no full instructions) to save context tokens. Call `get_skill` for the ones you need.

## Skill Loading

### Use pre-built dataset (recommended)

```bash
skill-mcp pull                    # merge 89K skills into your store
skill-mcp pull --include-index    # also download pre-built vector index
skill-mcp pull --replace          # replace local DB entirely (discard custom skills)
```

`pull` **merges by default** — your custom skills are preserved. The dataset includes LangSkills, SkillNet, Anthropic official, and community sources, already deduplicated.

### Add your own skills

Create `SKILL.md` files anywhere:

```markdown
---
name: "debug-memory-leak"
description: "Identify and fix memory leaks in long-running applications"
tags: ["debugging", "memory", "profiling"]
---

## Instructions

Your detailed skill instructions here...
```

Then import and index:

```bash
skill-mcp import --source directory --path ~/my-skills/
skill-mcp build-index             # incremental — only encodes new skills
```

### Mixed usage (HF + custom)

```bash
skill-mcp pull                    # 89K pre-built skills
skill-mcp import --source directory --path ~/my-skills/   # add yours
skill-mcp build-index             # encodes only your new skills, keeps the rest
```

Deduplication is automatic. Priority: ANTHROPIC > COMMUNITY > LANGSKILLS > SKILLNET.

## Embedding Backends

Default: `sentence-transformers/all-MiniLM-L6-v2` (384-dim, local, free, no API key).

| Backend | Install | Pre-built index | Requires |
|---------|---------|-----------------|----------|
| `sentence-transformers` | `pip install skill-retrieval-mcp[local]` | available via `--include-index` (137MB) | Nothing |
| `openai` | `pip install skill-retrieval-mcp[openai]` | available via `--include-index` (1.1GB) | `OPENAI_API_KEY` |
| `ollama` | `pip install skill-retrieval-mcp[ollama]` | not available, build locally | Ollama running |

`pull --include-index` downloads the pre-built index matching your configured backend. To switch backends:

```bash
# Option A: build locally with a different backend
skill-mcp build-index --backend openai --model text-embedding-3-large --force

# Option B: download pre-built index for a different backend
# 1. Update config (~/.skill-mcp/config.yaml):
#      embedding:
#        backend: openai
#        model: text-embedding-3-large
# 2. Then pull the matching index:
skill-mcp pull --include-index
```

One index = one embedding model. All vectors must come from the same model. `build-index` detects model changes and requires `--force` to rebuild.

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
pytest tests/ -v                  # 110 tests
```

Architecture, data model, and extension guide: [`dev.md`](dev.md)

## License

MIT
