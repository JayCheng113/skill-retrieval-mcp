---
name: "refactor-code"
description: "Disciplined approach to improving code structure without changing external behavior"
tags: ["coding", "refactoring", "clean-code", "maintainability"]
---

## Instructions

Refactoring improves the internal structure of code without altering its observable behavior. Always refactor with a safety net of tests.

**Before You Refactor**
1. Ensure the existing code is covered by passing tests. If tests are absent, write characterization tests first to capture current behavior.
2. Commit the current working state so you have a clean rollback point.
3. Identify the specific code smell you are addressing (see below).

**Common Code Smells and Fixes**
- **Long Method**: Break it into smaller, well-named helper functions. A function should do one thing.
- **Duplicate Code (DRY)**: Extract the repeated logic into a shared utility or base class.
- **Large Class / God Object**: Apply the Single Responsibility Principle — split into focused classes.
- **Magic Numbers/Strings**: Replace literals with named constants (`MAX_RETRIES = 3`).
- **Deep Nesting**: Invert conditions and return early to flatten arrow-code.
- **Long Parameter List**: Group related parameters into a data class or configuration object.
- **Feature Envy**: Move a method to the class whose data it uses most.

**Refactoring Workflow**
1. Make one small, focused change at a time.
2. Run the full test suite after each change — never accumulate multiple refactors before testing.
3. Commit each logical refactor separately with a descriptive message (`refactor: extract validate_user helper`).
4. Do not mix feature additions with refactoring in the same commit.

**When to Stop**
Stop when the code is clear, the tests pass, and the change does not add new functionality. Perfectionism is the enemy of shipping.
