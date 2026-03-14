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

Or register manually:

| Agent | Config file | Format |
|-------|------------|--------|
| **Claude Code** | `.mcp.json` (project) | `{"mcpServers": {"skill-retrieval": {"command": "skill-mcp", "args": ["serve"]}}}` |
| **Gemini CLI** | `~/.gemini/settings.json` | same JSON as above |
| **Cursor** | `.cursor/mcp.json` | same JSON as above |
| **Codex CLI** | `~/.codex/config.toml` | `[mcp_servers.skill-retrieval]`<br>`command = "skill-mcp"`<br>`args = ["serve"]` |

That's it. Your agent now has access to 89K searchable skills.

## How Your Agent Uses It

The server provides **server instructions** during MCP initialization, telling the agent what the knowledge base contains and how to use the tools. The agent then decides when to search based on the task at hand — no manual prompting needed.

The workflow is **search → fetch**:

```
Agent: search_skills({"query": "debug memory leak in python", "k": 3})
→ [{"id": "a1b2", "name": "debug-memory-leak", "score": 0.81, ...}, ...]

Agent: get_skill({"skill_id": "a1b2"})
→ {"instructions": "Memory leaks cause applications to consume increasing RAM..."}
```

`search_skills` returns summaries only (no instructions) to save context tokens. The agent calls `get_skill` for the ones it needs.

| Tool | When to use | What it returns |
|------|-------------|-----------------|
| `search_skills` | Semantic search — when the user describes a task in natural language | Top-k skill summaries with relevance scores |
| `keyword_search` | Keyword search — when you have specific terms (tool names, error messages) | Matching skill summaries via FTS5 |
| `get_skill` | After search — fetch full instructions for a skill you want to apply | Complete skill with step-by-step instructions |
| `list_categories` | Discovery — browse what domains are covered | Category names and skill counts |

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

You can switch to a different backend. We provide pre-built indexes for 89K skills on HuggingFace, so you don't have to re-embed them yourself:

| Backend | Install | Pre-built index for 89K skills | Requires |
|---------|---------|-------------------------------|----------|
| `sentence-transformers` (default) | `pip install skill-retrieval-mcp[local]` | available (137MB) | Nothing |
| `openai` | `pip install skill-retrieval-mcp[openai]` | available (1.1GB) | `OPENAI_API_KEY` |
| `ollama` | `pip install skill-retrieval-mcp[ollama]` | not available — build locally | Ollama running |

`pull --include-index` automatically downloads the pre-built index matching your configured backend. To use OpenAI embeddings with the pre-built index:

```bash
# 1. Edit ~/.skill-mcp/config.yaml:
#    embedding:
#      backend: openai
#      model: text-embedding-3-large
# 2. Download the matching pre-built index:
skill-mcp pull --include-index
```

To rebuild all vectors locally (required for ollama, or if you added custom skills):

```bash
skill-mcp build-index --backend ollama --model nomic-embed-text --force
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
