# skill-retrieval-mcp

> Your agent doesn't need 200K skills in context. It needs the right 5.

An MCP server that gives AI agents on-demand access to 89K+ skills covering virtually every technical domain — programming, DevOps, cloud, ML, databases, security, documentation, API design, testing, project management, and more. Search is < 5ms with zero API calls.

Works with **Claude Code**, **Codex CLI**, **Gemini CLI**, **Cursor**, and any MCP-compatible agent.

## Why

Traditional skill systems pre-load skills into context. This doesn't scale — you hit context limits at 10–20 skills, and the agent wastes tokens on irrelevant ones.

skill-retrieval-mcp flips the approach: **89K+ skills are always one search away**, and searching costs < 5ms with zero API calls. The agent searches as it works, the same way an engineer looks up documentation mid-task — whether the task is writing code, designing an API, setting up CI/CD, writing documentation, or anything else where best practices exist.

| | Pre-loading all skills | skill-retrieval-mcp |
|---|---|---|
| **Scale** | 10–20 skills | 89K+ |
| **Domain coverage** | Hand-picked | Virtually every technical domain |
| **Selection** | Manual, upfront | Semantic search, on-demand |
| **Search latency** | — | < 5ms |
| **Context cost** | Everything loaded | Top-k summaries only |
| **LLM calls for retrieval** | — | Zero (local FAISS) |

## How It Works

```
User: "Set up a FastAPI project with JWT auth and deploy to k8s"

Agent thinks: I need best practices for several things here.

  ① search_skills("FastAPI project structure best practices")
    → finds "fastapi-project-setup" (score: 0.89)

  ② get_skill("fastapi-project-setup")
    → reads full guide, starts implementing...

  ③ While writing auth, searches again:
    search_skills("JWT authentication FastAPI security")
    → finds "jwt-auth-fastapi" (score: 0.85)

  ④ While writing k8s manifests:
    search_skills("kubernetes deployment python application")
    → finds "k8s-deploy-python" (score: 0.82)
```

The agent constructs different queries at each step based on what it's currently working on. It doesn't search everything upfront — it searches **when it needs to**, with queries shaped by the task context.

## Get Started

### 1. Install

```bash
pip install "skill-retrieval-mcp[local,hf]"
```

`[local]` installs `sentence-transformers` for local query embedding. `[hf]` installs `huggingface-hub` for downloading the skill database.

### 2. Download skills and index

```bash
skill-mcp pull --include-index
```

This downloads from [HuggingFace](https://huggingface.co/datasets/zcheng256/skillretrieval-data):
- **89,267 skills** (960MB SQLite) — sourced from LangSkills, SkillNet, Anthropic official, and community contributions
- **Pre-built vector index** (137MB) — 384-dim vectors with `all-MiniLM-L6-v2`, ready for search

No local computation needed. To build the index yourself, omit `--include-index` and run `skill-mcp build-index` (~7 min on CPU).

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

## Tools

| Tool | Purpose | Returns |
|------|---------|---------|
| `search_skills` | Semantic search — natural language queries | Top-k summaries with relevance scores |
| `keyword_search` | Exact term matching — tool names, error messages, CLI commands | Matching summaries via FTS5 |
| `get_skill` | Fetch full instructions by ID (call after search) | Complete guide with code examples |
| `list_categories` | Browse available knowledge domains | Category names and counts |

The two-step **search → fetch** design saves context tokens: search results contain summaries only, the agent fetches full instructions only for skills it actually needs.

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

## Embedding Backends

The default `sentence-transformers/all-MiniLM-L6-v2` runs locally, requires no API key, and has a pre-built index ready to download.

| Backend | Install | Pre-built index | Requires |
|---------|---------|-----------------|----------|
| `sentence-transformers` (default) | `pip install skill-retrieval-mcp[local]` | 137MB | Nothing |
| `openai` | `pip install skill-retrieval-mcp[openai]` | 1.1GB | `OPENAI_API_KEY` |
| `ollama` | `pip install skill-retrieval-mcp[ollama]` | build locally | Ollama running |

To switch backend:

```bash
# Edit ~/.skill-mcp/config.yaml, then:
skill-mcp pull --include-index          # download pre-built index for your backend
# or
skill-mcp build-index --backend ollama --model nomic-embed-text --force  # build locally
```

One index = one embedding model. `build-index` detects mismatches and requires `--force` to rebuild.

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
pytest tests/ -v    # 132 tests, ~0.7s
```

Architecture, design decisions, and extension guide: [`dev.md`](dev.md)

## License

MIT
