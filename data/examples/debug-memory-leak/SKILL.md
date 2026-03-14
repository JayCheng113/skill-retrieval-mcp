---
name: "debug-memory-leak"
description: "Identify and fix memory leaks in long-running applications"
tags: ["debugging", "memory", "performance", "profiling"]
---

## Instructions

Memory leaks cause applications to consume increasing RAM over time, eventually leading to OOM crashes. A systematic profiling approach is essential.

**Step 1: Confirm the Leak**
Monitor RSS (Resident Set Size) over time using `top`, `htop`, or a metrics dashboard. A genuine leak shows monotonically increasing memory that does not free up after GC cycles. Rule out expected growth (caches, connection pools warming up).

**Step 2: Profile Memory Usage**

*Python*: Use `tracemalloc` (stdlib) or `memory_profiler`.
```python
import tracemalloc
tracemalloc.start()
# ... run suspect code ...
snapshot = tracemalloc.take_snapshot()
for stat in snapshot.statistics("lineno")[:10]:
    print(stat)
```

*Node.js*: Take a heap snapshot in Chrome DevTools (attach via `--inspect`) or use `heapdump`.

*Go*: Use `pprof` — expose `/debug/pprof/heap` and compare snapshots with `go tool pprof`.

*Java/JVM*: Use `jmap -histo <pid>` for a quick histogram, or take a full heap dump and analyze with Eclipse MAT or VisualVM.

**Step 3: Common Root Causes**
- **Unbounded caches or registries**: dictionaries/maps that grow forever because old entries are never evicted. Use `weakref` or LRU caches.
- **Event listener accumulation**: listeners added inside loops or request handlers without removal.
- **Circular references with `__del__`**: In Python pre-3.4, this prevented GC collection.
- **Thread-local storage**: objects stored per-thread that outlive the request lifecycle.
- **Large objects held in closures or global scope** longer than necessary.

**Step 4: Fix and Verify**
Apply the fix, deploy, and re-run the same load that triggered the leak. Confirm that memory stabilizes at a plateau rather than continuing to rise.
