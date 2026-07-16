# MONITORING

## Heartbeat

`HealthMonitor.tick()` runs every `TWA_HEARTBEAT_S` seconds.

* `ts`            — epoch seconds
* `cpu_pct`       — process CPU utilisation
* `rss_mb`        — resident memory
* `fds`           — open file descriptors
* `threads`       — Python threads
* `feeds.adapters.*.last_ok_ts` — adapter last successful fetch
* `feeds.adapters.*.last_error`  — last recoverable error

Record path: `data_dir/heartbeat.json` (rewritten in place).

## Per-adapter feed health

Each adapter records:
```python
{
  "exchange": "binance",
  "last_ok_ts": 1704067200.0,
  "last_error": null
}
```

## Manual health snapshot

```bash
twa health
```

prints a single heartbeat snapshot.

## Alerting recipe (example)

Pipe `journalctl -u twa.service -o cat -f` to Loki; alert on:
* `event=orchestrator.cycle_failed`  → once per minute is bad.
* `event=health.beat & cpu_pct > 85` for > 5 minutes.
* `feed.binance.last_error != null AND last_ok_ts < now - 600`.
