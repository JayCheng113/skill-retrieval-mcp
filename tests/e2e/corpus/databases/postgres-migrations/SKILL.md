---
name: postgres-migrations
description: Apply schema changes to a live PostgreSQL database without taking downtime or locking out writers.
category: databases
tags: [postgres, sql, migrations, ddl]
---

# PostgreSQL migrations without downtime

Adding a `NOT NULL` column to a large table rewrites it under an `ACCESS EXCLUSIVE`
lock, which blocks every reader and writer for the duration. Split it instead:

1. Add the column as nullable with no default.
2. Backfill in batches, committing between batches so the lock is never held long.
3. Add a `NOT VALID` check constraint, then `VALIDATE CONSTRAINT` separately —
   validation takes only a `SHARE UPDATE EXCLUSIVE` lock.

Dropping a column is metadata-only and safe. Renaming one is not: the old and new
name cannot both be live, so deploy a read-both/write-both shim first.

Always set `lock_timeout` before DDL. Without it a migration that cannot acquire
its lock will queue behind a long transaction and block everything behind it too.
