# Roadmap

## v0.2 — Quality & Ecosystem

- [ ] **MCP Prompts** — Expose `find-skills-for-task` prompt template so agents auto-retrieve skills at conversation start, not just via tool calls
- [ ] **Retrieval benchmark** — Eval set (query → expected skills) with Precision@k / MRR metrics; publish results per embedding backend so users can choose
- [ ] **Skill versioning** — `updated_at` field + `pull` shows diff summary (N new, N updated, N unchanged)

## v0.3 — Community

- [ ] **Contributing guide** — CONTRIBUTING.md with importer/backend extension walkthrough
- [ ] **Issue & PR templates** — Bug report, feature request, new importer
- [ ] **CHANGELOG.md** — Automated from git tags

## v0.4 — Intelligence

- [ ] **Usage-based re-ranking** — Track `get_skill` call frequency, boost frequently-used skills in search results
- [ ] **Skill quality scoring** — Auto-score skills by instruction length, tag coverage, source reliability; expose as search filter

## Future

- [ ] **Web UI** — Lightweight Streamlit/Gradio app for browsing skills, testing search, managing categories
- [ ] **Skill publishing** — `skill-mcp push` to share custom skills back to HuggingFace
- [ ] **Composite skills** — Reference other skills by ID within instructions, auto-fetch dependencies
