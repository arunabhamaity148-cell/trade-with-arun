# SYSTEM_DESIGN

## State store
All transient state lives *in memory*.  Persisted artefacts are:
* `data_dir/heartbeat.json`  — last health snapshot.
* `data_dir/signals.jsonl`   — append-only log of every emitted signal.

## Concurrency model
* One orchestrator coroutine driven by `asyncio.run`.
* One health coroutine (`asyncio.create_task`).
* One Telegram command-loop background task (if enabled).
* All exchange / news HTTP calls are async (`httpx.AsyncClient`).

There is **no shared mutable state between threads**.  The only shared
mutable state between tasks is the in-process:
* `CooldownBook._last` (writes are guarded by `time.time()` only — single
  writer, many readers, intentional — and the comparison is monotonic).
* `HealthMonitor._metrics` (single-writer, rare readers — race-free for
  the reader use cases in the codebase).

## Error handling philosophy
* A network exception from any single adapter → adapter returns `None` /
  empty, aggregator logs and continues.
* A cycle-level exception → orchestrator logs `cycle_failed` and proceeds.
* A persistent adapter failure → heartbeat writes
  `last_error` and `twa health` reports it.
* Loud, structured JSON logs everywhere; no print() noise in production.

## Shutdown
`Cmd+.` / Ctrl-C → `Orchestrator.run_forever` exits its loop, `stop()`
awaits the health and Telegram tasks, and closes the HTTP client.

## Memory budget
* Capped in-memory signal log (2 000 entries) — explicitly bounded.
* `TTLCache` items expire after `http_timeout_s` seconds; default 15.
* `HealthMonitor._metrics` capped at 256.
* `NewsGuard._cache` items older than 12 hours are purged.
