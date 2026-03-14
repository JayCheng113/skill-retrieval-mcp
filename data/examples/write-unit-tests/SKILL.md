---
name: "write-unit-tests"
description: "Best practices for writing effective, maintainable unit tests"
tags: ["coding", "testing", "unit-tests", "quality"]
---

## Instructions

Unit tests validate individual functions or classes in isolation. Good unit tests act as living documentation and catch regressions quickly.

**Test Structure: AAA Pattern**
Every test should follow Arrange → Act → Assert:
- **Arrange**: Set up the input data and any required dependencies (use mocks/stubs for external systems).
- **Act**: Call the single function or method under test.
- **Assert**: Verify the output or side effect with a specific, descriptive assertion.

**Naming Conventions**
Name tests so that a failure message reads like a sentence:
`test_calculate_total_returns_zero_for_empty_cart` is far more informative than `test1`.

**What to Test**
- Happy path: the expected, normal-case behavior.
- Boundary values: empty collections, zero, maximum integers, empty strings.
- Error paths: ensure exceptions are raised (or not raised) appropriately.
- Each public method of the unit under test.

**What to Avoid**
- Do not test private implementation details; test observable behavior.
- Avoid multiple unrelated assertions in a single test — one logical concept per test.
- Never make tests dependent on execution order or shared mutable state.
- Do not hit real databases, filesystems, or network endpoints — mock them.

**Code Coverage**
Aim for 80%+ line coverage as a baseline, but prioritize covering critical business logic and error branches over chasing 100%.

After writing tests, run them in a clean environment to confirm they all pass in isolation and as a suite.
