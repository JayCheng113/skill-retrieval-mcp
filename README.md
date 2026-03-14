# skill-retrieval-mcp

> Your agent doesn't need you to find the right skills. It needs to search 89K of them on its own.

An MCP server that gives AI agents on-demand access to **89K+ skills** covering virtually every technical domain. The agent searches as it works — the same way you look up docs mid-task.

Works with **Claude Code**, **Codex CLI**, **Gemini CLI**, **Cursor**, and any MCP-compatible agent.

## The Problem

You give your agent a skill — "always use TDD," "follow this API style" — and it works. But manually installing skills doesn't scale:

- **You don't know what exists.** There are thousands of skills out there. You install the 10 you happen to find — everything else, the agent guesses.
- **You can't install what you can't name.** Mid-task, the agent needs a skill for "OIDC-based PyPI publishing" — but you'd never think to install that in advance.
- **89K skills can't live in `~/.claude/skills/`.** Even with lazy loading, thousands of skill descriptions bloat the system prompt.

## The Fix

Don't install skills upfront. **Search them at runtime.**

```
You: "Help me set up CI/CD for this Python project"

─── Step 1: Agent searches ───────────────────────────────────────────

Agent: search_skills("github actions python CI pipeline")        ← 3ms
     → 5 results (summaries only, no full instructions):
       1. "github-actions-python"    (0.91) - CI/CD pipelines for Python with pytest and linting
       2. "github-actions-docker"    (0.72) - Docker build and push in GitHub Actions
       3. "gitlab-ci-python"         (0.68) - GitLab CI/CD for Python projects
       4. "circleci-python"          (0.61) - CircleCI configuration for Python
       5. "jenkins-pipeline"         (0.45) - Jenkins declarative pipelines

─── Step 2: Agent reads descriptions, picks #1 ──────────────────────

Agent: get_skill("github-actions-python")
     → gets full guide: step-by-step setup, matrix testing, caching, best practices
     → writes .github/workflows/ci.yml

─── Step 3: New need emerges mid-task ────────────────────────────────

Agent: # workflow needs PyPI publishing — search again with different query
       search_skills("pypi publish trusted publisher")           ← 2ms
     → "pypi-trusted-publishing" (0.87) - OIDC-based PyPI publishing without API keys
     → reads guide, adds publish step
```

Key behaviors:

- **Search returns summaries, not full instructions** — the agent reads descriptions and scores to decide which skills are worth fetching. 5 results searched, 1 skill read → 80% token savings.
- **The agent searches multiple times** as the task evolves. Different phase → different query → different skill.
- **Queries are shaped by context.** The second search includes "trusted publisher" — a term the agent picked up while working, not something the user said.

89K skills. < 5ms search. Zero LLM calls. Runs locally.

| | Installing skills manually | skill-retrieval-mcp |
|---|---|---|
| **Scale** | Dozens, if you're diligent | 89K+ |
| **Discovery** | You find and install each one | Agent searches by need |
| **Selection** | You pick upfront | Agent picks per-task |
| **Search** | Name matching on descriptions | Semantic, < 5ms, local FAISS |

## Quick Start

Three commands. Takes about 2 minutes (mostly download time).

```bash
# 1. Install
pip install "skill-retrieval-mcp[local,hf]"

# 2. Download 89K skills + pre-built vector index
skill-mcp pull --include-index

# 3. Register with your agent (auto-detects Claude Code, Cursor, etc.)
skill-mcp init
```

Done. Your agent now searches 89K skills on demand.

<details>
<summary>Manual registration (if <code>init</code> doesn't detect your agent)</summary>

| Agent | Config file | Add this |
|-------|------------|----------|
| **Claude Code** | `.mcp.json` | `{"mcpServers": {"skill-retrieval": {"command": "skill-mcp", "args": ["serve"]}}}` |
| **Gemini CLI** | `~/.gemini/settings.json` | same as above |
| **Cursor** | `.cursor/mcp.json` | same as above |
| **Codex CLI** | `~/.codex/config.toml` | `[mcp_servers.skill-retrieval]`<br>`command = "skill-mcp"`<br>`args = ["serve"]` |

</details>

## What's In the Knowledge Base

89,267 skills across every major technical domain, sourced from [LangSkills](https://github.com/langskills), [SkillNet](https://github.com/SkillNet), Anthropic official, and community contributions.

Each skill is a structured best-practice guide — not a one-liner, but a step-by-step how-to with code examples, common pitfalls, and recommendations.

Run `skill-mcp status` to see what you have locally, or use `list_categories` to browse domains.

## Tools

| Tool | What it does |
|------|-------------|
| `search_skills` | Semantic search — describe what you need in natural language |
| `keyword_search` | Exact match — tool names, error messages, CLI commands |
| `get_skill` | Fetch full instructions (call after search) |
| `list_categories` | Browse available domains and counts |

Search returns summaries only (saves tokens). The agent calls `get_skill` for the ones it actually needs.

## Add Your Own Skills

```markdown
<!-- ~/my-skills/deploy-checklist/SKILL.md -->
---
name: "deploy-checklist"
description: "Pre-deployment verification checklist for production releases"
tags: ["deployment", "production", "checklist"]
---

## Steps

1. Run full test suite...
2. Check database migrations...
```

```bash
skill-mcp import --source directory --path ~/my-skills/
# index is updated automatically — new skills are searchable immediately
```

No manual `build-index` needed. The import detects your existing index and incrementally adds only the new skills. Use `--no-index` to skip this (e.g. when batch-importing from multiple sources).

Custom skills merge with the pre-built ones. Deduplication is automatic.

## Embedding Backends

Default: `sentence-transformers/all-MiniLM-L6-v2` — local, free, no API key. Pre-built index included.

| Backend | Pre-built index | Requires |
|---------|-----------------|----------|
| `sentence-transformers` (default) | 137MB | Nothing |
| `openai` | 1.1GB | `OPENAI_API_KEY` |
| `ollama` | build locally | Ollama running |

```bash
# Switch to OpenAI embeddings:
# 1. Edit ~/.skill-mcp/config.yaml (set backend: openai, model: text-embedding-3-large)
# 2. Download matching index:
skill-mcp pull --include-index
```

## CLI Reference

```
skill-mcp init [--no-register]               Setup + register with agents
skill-mcp pull [--replace] [--include-index]  Download skills from HuggingFace
skill-mcp import --source SOURCE --path PATH  Import custom skills
skill-mcp build-index [--backend B] [--force] Build/update vector index
skill-mcp serve [--transport stdio|sse]       Start MCP server
skill-mcp search QUERY [--k N]               Test search from terminal
skill-mcp status                              Show what's loaded
skill-mcp dedup                               Remove duplicates
```

All commands support `--data-dir DIR` or env `SKILL_MCP_DATA_DIR`.

## Development

```bash
git clone https://github.com/JayCheng113/skill-retrieval-mcp
cd skill-retrieval-mcp
pip install -e ".[all,dev]"
pytest tests/ -v    # 139 tests, ~0.7s
```

Architecture and design decisions: [`dev.md`](dev.md)

## License

MIT
