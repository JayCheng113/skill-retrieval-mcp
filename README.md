# skill-retrieval-mcp

[![PyPI](https://img.shields.io/pypi/v/skill-retrieval-mcp.svg)](https://pypi.org/project/skill-retrieval-mcp/)
[![Python](https://img.shields.io/pypi/pyversions/skill-retrieval-mcp.svg)](https://pypi.org/project/skill-retrieval-mcp/)
[![License](https://img.shields.io/pypi/l/skill-retrieval-mcp.svg)](https://github.com/JayCheng113/skill-retrieval-mcp/blob/main/LICENSE)
[![CI](https://github.com/JayCheng113/skill-retrieval-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/JayCheng113/skill-retrieval-mcp/actions/workflows/ci.yml)

Semantic search over a licence-vetted corpus of 374 agent skills, served to your
coding agent over MCP. Runs locally, answers in single-digit milliseconds, makes
zero API calls.

Works with **Claude Code**, **Codex CLI**, **Gemini CLI**, **Cursor**, **OpenClaw**,
**Hermes**, and any MCP-compatible agent.

```
You: "Deploy this service to GKE"

─── Step 1: the agent searches ───────────────────────────────────────

Agent: search_skills("deploy a containerised service on kubernetes")   ← 6ms
     → 5 results (summaries only, no full instructions):
       1. "gke-service-networking"   (0.56) - Gateway API, Ingress, Cloud Armor, NEGs, managed SSL
       2. "gke-workload-scaling"     (0.51) - HPA and VPA for GKE workloads
       3. "gke-manifest-generation"  (0.51) - Production-ready Kubernetes YAML for Autopilot/Standard
       4. "gke-app-onboarding"       (0.46) - Containerizing and deploying an app to GKE for the first time
       5. "gke-basics"               (0.44) - Cluster provisioning, credentials, Autopilot vs Standard

─── Step 2: it reads the descriptions and picks #4, not #1 ───────────

Agent: get_skill("gke-app-onboarding")
     → gets the full guide: containerization, manifests, migration path
     → writes the Dockerfile and deployment.yaml

─── Step 3: a new need emerges mid-task ──────────────────────────────

Agent: # the service has to survive traffic spikes — search again
       search_skills("autoscale pods on cpu and memory")               ← 6ms
     → "gke-workload-scaling" (0.61) - Horizontal and Vertical Pod Autoscaler for GKE
     → reads the guide, adds the HPA manifest
```

Both searches are real output from the shipped corpus, not an illustration.
Three things in it are the whole design:

- **Search returns summaries, not instructions.** Five summaries cost a few
  hundred tokens; the one skill the agent actually reads costs about 2,400.
- **The top hit is not always the right one.** The agent picked #4 because its
  description says *for the first time* — a judgement no ranking can make. That
  is why search hands back descriptions instead of injecting the winner.
- **The agent searches again as the task evolves.** Neither "autoscale" nor
  "pods" appeared in what the user asked for.

## Installation

```bash
pip install "skill-retrieval-mcp[local,hf]"
skill-mcp pull --include-index      # corpus + pre-built vector index
skill-mcp init                      # detect and register with your agents
```

About two minutes, mostly download. `init` finds the agents you have installed
and writes their config for you.

<details>
<summary>Registering by hand</summary>

`init` writes `.mcp.json`, `~/.gemini/settings.json`, `.cursor/mcp.json` and
`~/.codex/config.toml` itself. For OpenClaw and Hermes it calls their own
`mcp add`, because both keep MCP servers inside a larger hand-edited config and
re-serialising it here would drop your comments. DeepSeek Harness has no
`mcp add`, so `init` prints the row for you to paste.

If it misses your agent, register this entry yourself:

```json
{
  "mcpServers": {
    "skill-retrieval": {
      "command": "/absolute/path/to/skill-mcp",
      "args": ["--data-dir", "/absolute/path/to/data-dir", "serve"]
    }
  }
}
```

Two details are load-bearing, and both fail silently if you shorten them:

- **`command` has to be an absolute path**, not `skill-mcp`. The agent resolves
  the name itself, from a session whose `PATH` has routinely never seen the venv
  or pipx directory you installed into. `which skill-mcp` gives you the value.
- **`--data-dir` has to be spelled out, and it has to come before `serve`.**
  `~` is re-resolved in whatever environment the agent spawns the server from,
  and the config that records your choice lives *inside* the chosen directory,
  so nothing else can recover it. A server opened on the wrong directory starts
  cleanly, lists its tools, and answers every search with nothing.
  `skill-mcp status` prints the resolved directory to use.

</details>

## Why search instead of install

Installing skills by hand works, right up until it doesn't scale:

- **You don't know what exists.** You install the ten you happen to find.
  Everything else, the agent guesses at.
- **You can't install what you can't name.** Mid-task the agent needs a skill
  for "OIDC-based PyPI publishing" — you would never have thought to add it.
- **A skill library doesn't fit in the prompt.** Lazy loading still puts every
  skill's name and description in front of the model: 37K tokens for this
  corpus before it has read a single one. The instructions are another 960K.

| | Installing by hand | skill-retrieval-mcp |
|---|---|---|
| **Scale** | Dozens, if you're diligent | 374 across 8 upstream repos |
| **Discovery** | You find and install each one | The agent searches by need |
| **Selection** | You pick upfront | The agent picks per task |
| **Matching** | Name matching on descriptions | Semantic, single-digit ms, local FAISS |
| **Provenance** | Whatever you happened to clone | Every skill carries its repo, URL and SPDX licence |

On 43 held-out queries phrased the way an agent would phrase a task — never
echoing a skill's own name — the shipped corpus answers **81.4% at rank 1 and
90.7% within the top 3**. The harness is in the repo; see
[`dev.md`](dev.md#the-retrieval-eval) for what it measures and what it found.

## What's in the corpus

374 skills from eight repositories whose licences were read before anything was
imported:

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

Each skill is a step-by-step guide with code examples, pitfalls and
recommendations — not a one-liner. The median runs about 9,600 characters.

Every row records the repository it came from, its upstream URL and its SPDX
licence, so anything you get back can be traced and attributed. Repositories
without a licence permitting redistribution are not imported, however good the
content.

`skill-mcp status` shows what you have locally.

## Tools

| Tool | What it does |
|------|-------------|
| `search_skills` | Semantic search — describe what you need in natural language |
| `keyword_search` | Exact match — tool names, error messages, CLI commands |
| `get_skill` | Fetch full instructions; call after searching |
| `list_categories` | Browse available domains and counts |

Search returns summaries only. The agent calls `get_skill` for the ones it
actually wants, which is where the token saving comes from.

## Adding your own skills

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
```

The index updates automatically — new skills are searchable immediately, and
only the new ones are embedded. Pass `--no-index` to skip that when you are
batch-importing several sources before one build. Your skills merge with the
corpus; deduplication is automatic.

## Configuration

Everything lives in one data directory, `~/.skill-mcp` by default:

```
~/.skill-mcp/
├── config.yaml
├── skills.db          # SQLite + FTS5
└── index/             # FAISS
```

Point somewhere else with the global `--data-dir` flag or `SKILL_MCP_DATA_DIR`.
The flag belongs to the group, so it goes **before** the subcommand:

```bash
skill-mcp --data-dir /srv/skills pull
```

### Embedding backends

The default is `sentence-transformers/all-MiniLM-L6-v2` — local, free, no API
key, and the one the pre-built index was built with.

| Backend | Pre-built index | Requires |
|---------|-----------------|----------|
| `sentence-transformers` (default) | yes | nothing |
| `openai` | build locally | `OPENAI_API_KEY` |
| `ollama` | build locally | Ollama running |

An index is only valid for the model that built it, so switching means
rebuilding:

```bash
# set backend: openai, model: text-embedding-3-large in config.yaml, then
skill-mcp build-index --backend openai
```

## CLI reference

```
skill-mcp [--data-dir DIR] [--log-level LEVEL] COMMAND [ARGS]

  init [--data-dir DIR] [--no-register]        Set up the data directory, register with agents
  pull [--replace] [--include-index]           Download the corpus from HuggingFace
  import --source SOURCE --path PATH           Import your own skills
       [--no-index]
  build-index [--backend B] [--model M]        Build or update the vector index
       [--force]
  serve [--transport stdio|sse]                Start the MCP server
  search QUERY [--k N]                         Search from the terminal
  status                                       Show what is loaded
  dedup                                        Remove cross-source duplicates
```

## Contributing

Issues and pull requests are welcome at
[github.com/JayCheng113/skill-retrieval-mcp](https://github.com/JayCheng113/skill-retrieval-mcp/issues).
[`dev.md`](dev.md) documents the architecture and the reasoning behind the
design decisions, including what was tried and rejected — read it before a
non-trivial change.

To propose a repository for the corpus, open an issue with its licence and a
case for what it covers that the current 374 do not. The bar is in
[`dev.md`](dev.md#adding-a-repository-to-the-curated-corpus): a licence that
permits redistribution, and evidence the skills actually win queries.

```bash
git clone https://github.com/JayCheng113/skill-retrieval-mcp
cd skill-retrieval-mcp
pip install -e ".[all,dev]"
pytest tests/ -v    # 240 tests, ~6s
```

## License

MIT — see [`LICENSE`](LICENSE).
