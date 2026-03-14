---
name: "debug-python"
description: "Systematic techniques for debugging Python applications efficiently"
tags: ["debugging", "python", "troubleshooting"]
---

## Instructions

Effective Python debugging means narrowing the problem space systematically rather than guessing and re-running.

**Step 1: Read the Traceback Carefully**
Python tracebacks are read bottom-up. The last line is the exception type and message. The frame just above it is where the error was raised. Read upward to find the first frame in *your* code — that is usually where to start.

**Step 2: Reproduce with a Minimal Example**
Isolate the failing logic into the smallest possible script. This removes noise and often reveals the root cause by itself.

**Step 3: Use the Debugger (pdb / breakpoint)**
Insert `breakpoint()` (Python 3.7+) directly before the suspected line. Inside pdb:
- `n` — step to next line
- `s` — step into a function call
- `p <expr>` — print the value of an expression
- `l` — list surrounding source
- `q` — quit the debugger

For Django/Flask apps, use `python -m pdb manage.py runserver` or configure the IDE debugger.

**Step 4: Inspect State with Logging**
Prefer `logging` over `print`. Set the level to `DEBUG` during investigation and revert before committing. Log the type and value of variables near the failure.

**Step 5: Check Common Python Pitfalls**
- Mutable default arguments (`def f(x=[]):`) accumulate state across calls.
- Late binding in closures inside loops captures the loop variable by reference.
- `is` vs `==`: use `==` for value comparison, `is` only for identity (`None`, singletons).
- Encoding errors often mean bytes/str confusion — check `decode()`/`encode()` calls.

**Step 6: Verify Assumptions with Assertions**
Add `assert isinstance(x, int), f"Expected int, got {type(x)}"` to make implicit assumptions explicit while debugging.
