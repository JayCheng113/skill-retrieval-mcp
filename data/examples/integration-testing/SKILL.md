---
name: "integration-testing"
description: "Strategy for writing integration tests that validate component interactions reliably"
tags: ["testing", "integration-testing", "quality", "backend"]
---

## Instructions

Integration tests verify that multiple components work correctly together — a service talking to a real database, an HTTP handler processing a real request, or a queue consumer processing real messages.

**Scope: What to Cover**
- Database layer: test that queries, transactions, and schema constraints work as expected against a real (test) database.
- HTTP layer: test request routing, middleware (auth, rate limiting), serialization, and response codes end-to-end.
- External service integrations: use a test double (mock server, WireMock, VCR cassette) at the network boundary to avoid relying on live third-party services.

**Test Environment Setup**
- Use Docker Compose to spin up real dependencies (PostgreSQL, Redis, RabbitMQ) for the test run.
- Run migrations before the suite and wrap each test in a transaction that rolls back, or truncate tables between tests, to ensure isolation.
- Store connection strings and secrets in environment variables; never hardcode them.

**Test Design**
- Each integration test should exercise a complete user-visible scenario, not a single internal function.
- Seed only the data your test needs — over-seeding makes failures hard to diagnose.
- Test unhappy paths: what happens when the database is at capacity, or a downstream service returns 503?
- Keep tests deterministic: avoid `time.Now()` or random IDs without seeding — use fixed timestamps and UUID generation that can be controlled.

**Speed and CI**
- Integration tests are inherently slower than unit tests. Group them in a separate test suite/marker so developers can run unit tests locally and integration tests in CI.
- Parallelize independent tests at the file or test-class level, but share the database container across the suite to avoid startup overhead.
- Fail fast: if the database container fails to start, abort the suite immediately rather than running every test to timeout.
