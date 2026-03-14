---
name: "write-readme"
description: "Craft a README that helps new users and contributors get started quickly"
tags: ["documentation", "readme", "open-source", "developer-experience"]
---

## Instructions

A README is the front door of your project. It should answer the most common questions a visitor has within 60 seconds.

**Required Sections**
1. **Project title and one-line description**: What does this project do and who is it for?
2. **Badges** (optional but useful): build status, coverage, license, latest version.
3. **Why / Motivation**: What problem does this solve? Why should someone choose this over alternatives?
4. **Quick Start**: The fastest path from zero to a running example. Target under 5 commands.
5. **Installation**: Full, OS-specific installation instructions including prerequisites (Node version, Python version, system libraries).
6. **Usage**: Show the most common use cases with code examples. Use syntax highlighting in fenced code blocks.
7. **Configuration**: Document all environment variables or configuration file options with their defaults.
8. **Contributing**: Link to `CONTRIBUTING.md` or provide a brief guide (fork → branch → PR).
9. **License**: State the license and link to `LICENSE`.

**Writing Tips**
- Use short paragraphs and bullet points — developers scan, they do not read linearly.
- Test your Quick Start on a clean machine or container to verify it actually works.
- Include screenshots or an animated GIF for GUI tools or CLIs with rich output.
- Keep the README truthful: outdated docs are worse than no docs because they waste time.

**Maintenance**
Update the README as part of every PR that changes behavior, configuration, or installation steps. Treat it like code — stale documentation is a bug.
