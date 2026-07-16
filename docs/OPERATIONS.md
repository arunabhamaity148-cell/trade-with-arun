# OPERATIONS

## Daily checklist (paper)

1. `twa config` → confirm `TWA_ENV=paper`.
2. `twa health` → confirm at least one exchange reports `last_ok_ts`
   with a small `last_error` value.
3. `twa signals --limit 20` → spot-check the last few signals for
   sane ATR-based invalidation (±1.5 ATR from close).

## Restart

* `Ctrl-C` → orchestrator exits cleanly.
* Send SIGTERM (`kill -TERM <pid>`) → same behaviour (asyncio drains).
* Crash → systemd will restart on `Restart=on-failure`.

## Log format
`structlog` JSON: `{"event":..., "level":..., "timestamp":...}`.
Tail with `jq`:

```bash
journalctl -u twa.service -o cat | jq -c .
```

## Add a new symbol

1. Append the symbol to `TWA_SYMBOLS`.
2. Restart the service.
3. Verify with `twa health`.

## Disable an exchange

1. Remove the name from `TWA_EXCHANGES`.
2. Restart the service.

No code changes are required.

## Disable the News Guard

Set `TWA_NEWS_ENABLED=false`.  News dampening will silently be 1.0.
