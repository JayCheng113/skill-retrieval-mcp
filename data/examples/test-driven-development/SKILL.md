---
name: "test-driven-development"
description: "Apply the Red-Green-Refactor TDD cycle to drive design and prevent regressions"
tags: ["testing", "tdd", "design", "quality"]
---

## Instructions

Test-Driven Development (TDD) is a discipline where you write a failing test before writing any production code. The goal is better design and a comprehensive regression suite, not just test coverage.

**The Red-Green-Refactor Cycle**
1. **Red**: Write the smallest possible test for the next piece of desired behavior. Run it and watch it fail — this confirms the test is actually testing something.
2. **Green**: Write the minimum production code needed to make the test pass. Do not over-engineer; the goal is green, not beautiful.
3. **Refactor**: With the test suite passing, improve the design of both the production code and the test. Remove duplication, rename for clarity, extract abstractions. Run tests again to confirm they still pass.

**What to Test First**
- Start with the simplest degenerate case (empty input, zero, null).
- Progress to the core happy path.
- Add edge cases and error paths one at a time.

**Common Pitfalls**
- Writing too large a test in the Red step — if you cannot make it green in under 10 minutes, split it into smaller steps.
- Skipping the Refactor step — TDD without refactoring accumulates mess as fast as any other approach.
- Testing implementation details instead of behavior — tests should survive internal refactors.

**When TDD Shines**
TDD works best for business logic, algorithms, and data transformation layers. It is harder to apply to UI, exploratory/spike code, and infrastructure glue — it is acceptable to write tests after for those cases.

**Getting Started on an Existing Codebase**
Apply TDD to all new code and bug fixes. When fixing a bug, first write a test that reproduces it, then fix the code. This ensures the bug cannot silently return.
