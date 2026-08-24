# skill-retrieval-mcp

> Your agent doesn't need you to pick the right skill. It needs to search for one on its own.

An MCP server that gives AI agents on-demand access to a licence-vetted corpus of agent skills, collected from seven upstream repositories. The agent searches as it works — the same way you look up docs mid-task.

Works with **Claude Code**, **Codex CLI**, **Gemini CLI**, **Cursor**, and any MCP-compatible agent.

## The Problem

You give your agent a skill — "always use TDD," "follow this API style" — and it works. But manually installing skills doesn't scale:

- **You don't know what exists.** There are thousands of skills out there. You install the 10 you happen to find — everything else, the agent guesses.
- **You can't install what you can't name.** Mid-task, the agent needs a skill for "OIDC-based PyPI publishing" — but you'd never think to install that in advance.
- **A skill library doesn't fit in the prompt.** Lazy loading still puts every skill's name and description in front of the model — 37K tokens for this corpus, before the agent has read a single one. The instructions themselves are another 960K.

## The Fix

Don't install skills upfront. **Search them at runtime.**

```
You: "Deploy this service to GKE"

─── Step 1: Agent searches ───────────────────────────────────────────

Agent: search_skills("deploy a containerised service on kubernetes")   ← 4ms
     → 5 results (summaries only, no full instructions):
       1. "gke-service-networking"   (0.56) - Gateway API, Ingress, Cloud Armor, NEGs, managed SSL
       2. "gke-workload-scaling"     (0.51) - HPA and VPA for GKE workloads
       3. "gke-manifest-generation"  (0.51) - Production-ready Kubernetes YAML for Autopilot/Standard
       4. "gke-app-onboarding"       (0.46) - Containerizing and deploying an app to GKE for the first time
       5. "gke-basics"               (0.44) - Cluster provisioning, credentials, Autopilot vs Standard

─── Step 2: Agent reads the descriptions and picks #4, not #1 ────────

Agent: get_skill("gke-app-onboarding")
     → gets full guide: containerization, manifests, migration path
     → writes the Dockerfile and deployment.yaml

─── Step 3: New need emerges mid-task ────────────────────────────────

Agent: # the service has to survive traffic spikes — search again
       search_skills("autoscale pods on cpu and memory")               ← 4ms
     → "gke-workload-scaling" (0.61) - Horizontal and Vertical Pod Autoscaler for GKE
     → reads guide, adds the HPA manifest
```

Key behaviors:

- **Search returns summaries, not full instructions** — the agent reads descriptions and scores to decide which skills are worth fetching. Five summaries cost a few hundred tokens; the one skill it actually reads costs about 2,400.
- **The top hit is not always the right one.** The agent picked #4 because its description says "for the first time" — a judgement the ranking can't make. That is why search returns descriptions instead of auto-injecting the winner.
- **The agent searches again as the task evolves.** Neither "autoscale" nor "pods" appeared in what the user asked for; those are terms the agent picked up while writing the manifest.

Both searches above are real output from the shipped corpus, not an illustration.

< 5ms search, measured end to end including query embedding. Zero LLM calls. Runs locally.

| | Installing skills manually | skill-retrieval-mcp |
|---|---|---|
| **Scale** | Dozens, if you're diligent | 374 across 8 upstream repos |
| **Discovery** | You find and install each one | Agent searches by need |
| **Selection** | You pick upfront | Agent picks per-task |
| **Search** | Name matching on descriptions | Semantic, < 5ms, local FAISS |
| **Provenance** | Whatever you happened to clone | Every skill carries its repo, URL and SPDX licence |

## Quick Start

Three commands. Takes about 2 minutes (mostly download time).

```bash
# 1. Install
pip install "skill-retrieval-mcp[local,hf]"

# 2. Download the skill corpus + pre-built vector index
skill-mcp pull --include-index

# 3. Register with your agent (auto-detects Claude Code, Cursor, etc.)
skill-mcp init
```

Done. Your agent now searches the corpus on demand.

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

374 skills, collected from eight repositories whose licences were read before anything was imported:

| Repository | Skills | Licence |
|------------|--------|---------|
| [K-Dense-AI/scientific-agent-skills](https://github.com/K-Dense-AI/scientific-agent-skills) | 163 | MIT |
| [google/skills](https://github.com/google/skills) | 112 | Apache-2.0 |
| [mattpocock/skills](https://github.com/mattpocock/skills) | 35 | MIT |
| [addyosmani/agent-skills](https://github.com/addyosmani/agent-skills) | 24 | MIT |
| [anthropics/skills](https://github.com/anthropics/skills) | 20 | Apache-2.0 |
| [obra/superpowers](https://github.com/obra/superpowers) | 14 | MIT |
| [kepano/obsidian-skills](https://github.com/kepano/obsidian-skills) | 5 | MIT |
| [Agents365-ai/drawio-skill](https://github.com/Agents365-ai/drawio-skill) | 1 | MIT |

Each skill is a structured best-practice guide — not a one-liner, but a step-by-step how-to with code examples, common pitfalls, and recommendations. The median one runs about 9,600 characters.

Every row records the repository it came from, its upstream URL and its SPDX licence, so anything you get back can be traced and attributed. Repositories without a licence permitting redistribution are not imported, even when their content is good.

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
| `sentence-transformers` (default) | yes | Nothing |
| `openai` | build locally | `OPENAI_API_KEY` |
| `ollama` | build locally | Ollama running |

```bash
# Switch to OpenAI embeddings:
# 1. Edit ~/.skill-mcp/config.yaml (set backend: openai, model: text-embedding-3-large)
# 2. Build the matching index — an index is only valid for the model that built it:
skill-mcp build-index --backend openai
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
pytest tests/ -v    # 143 tests, ~0.7s
```

Architecture and design decisions: [`dev.md`](dev.md)

## License

MIT — see [`LICENSE`](LICENSE).
