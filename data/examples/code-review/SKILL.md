---
name: "code-review"
description: "Systematic guide for conducting thorough and constructive code reviews"
tags: ["coding", "review", "quality", "best-practices"]
---

## Instructions

When reviewing code, follow a structured approach that balances thoroughness with constructive feedback.

**Before Starting**
- Understand the purpose of the change by reading the PR description, linked issues, and any relevant context.
- Run the code locally if the change is non-trivial.

**Review Checklist**
1. **Correctness**: Does the code do what it claims? Look for off-by-one errors, null pointer dereferences, and incorrect conditionals.
2. **Readability**: Are variable and function names descriptive? Is the code self-documenting? Flag any section that required re-reading.
3. **Edge Cases**: Does the code handle empty inputs, large datasets, concurrent access, and error states?
4. **Performance**: Identify unnecessary loops, redundant database queries (N+1 problems), or blocking I/O in hot paths.
5. **Security**: Check for SQL injection, XSS, insecure deserialization, and hardcoded secrets.
6. **Test Coverage**: Verify that new logic is covered by unit or integration tests. Tests should test behavior, not implementation.
7. **Consistency**: Ensure the code follows the existing project conventions and style guide.

**Giving Feedback**
- Prefix comments with tags: `nit:` for minor style issues, `blocker:` for must-fix issues, `question:` for clarifications.
- Explain the *why* behind every blocker — link to docs or standards when possible.
- Praise good patterns you notice; reviews should be encouraging as well as critical.
- Suggest specific alternatives rather than just identifying problems.

Aim to complete the review within one business day to keep the author unblocked.
