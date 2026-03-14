---
name: "git-commit-message"
description: "Write clear, consistent git commit messages following the Conventional Commits standard"
tags: ["git", "version-control", "conventions"]
---

## Instructions

A well-written commit message makes the project history navigable, aids code review, and enables automated changelog generation.

**The Conventional Commits Format**
```
<type>(<optional scope>): <short summary>

<optional body>

<optional footer>
```

**Types**
- `feat`: a new feature visible to users
- `fix`: a bug fix
- `refactor`: code restructuring without behavior change
- `test`: adding or updating tests
- `docs`: documentation changes only
- `chore`: build scripts, dependency updates, tooling
- `perf`: performance improvements
- `ci`: changes to CI/CD configuration

**Writing the Summary Line**
- Keep it under 72 characters.
- Use imperative mood: "add login endpoint" not "added" or "adds".
- Do not end with a period.
- Be specific: "fix null pointer in UserService.getById" beats "fix bug".

**Writing the Body (when needed)**
- Separate from the summary with a blank line.
- Explain *what* changed and *why*, not *how* (the diff shows how).
- Wrap lines at 72 characters.
- Reference issue numbers: `Closes #42` or `Refs #101`.

**Examples**
```
feat(auth): add OAuth2 login with Google

Users can now sign in using their Google account. This removes the need
to manage a separate password for many users.

Closes #88
```

```
fix(cart): prevent negative quantity on item removal
```

**What to Avoid**
- Vague messages: "fix", "update", "WIP", "misc changes".
- Bundling multiple unrelated changes into one commit — prefer atomic commits.
