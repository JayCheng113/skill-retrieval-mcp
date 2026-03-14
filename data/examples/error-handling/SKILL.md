---
name: "error-handling"
description: "Design robust error handling strategies for reliable, observable applications"
tags: ["api-design", "error-handling", "reliability", "backend"]
---

## Instructions

Robust error handling makes applications predictable for callers and diagnosable for operators. Treat errors as first-class citizens in your design.

**Classify Errors First**
- **Operational errors** (expected failures): invalid input, resource not found, network timeout, downstream service unavailable. These should be caught, logged at an appropriate level, and returned to the caller with a useful message.
- **Programmer errors** (bugs): null dereference, type mismatches, assertion failures. These should crash loudly in development and be caught by a top-level handler in production that logs the full stack trace and returns a generic 500.

**Principles**
1. **Fail fast**: Validate inputs at the boundary (request handler, function entry point) before doing any work. Return 400/422 with specific field-level error messages.
2. **Never swallow exceptions silently**: An empty `catch {}` block is almost always wrong. At minimum, log the error.
3. **Use typed/structured errors**: Define a hierarchy of error classes (e.g., `ValidationError`, `NotFoundError`, `ConflictError`) so callers can handle them selectively.
4. **Include actionable messages**: Error messages are for humans. "User ID must be a positive integer, got -5" is better than "Invalid input".
5. **Propagate context**: When wrapping exceptions, include the original cause: `raise DatabaseError("Failed to fetch user") from original_exc`.

**Retries and Idempotency**
- Only retry idempotent operations or those with idempotency keys.
- Use exponential back-off with jitter for transient failures.
- Set a maximum retry budget to avoid amplifying a downstream outage.

**Logging and Observability**
- Log at the point of origin, not at every catch site — avoid duplicate log lines.
- Include a correlation/request ID in every log line and error response body so traces can be joined across services.
