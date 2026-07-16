# DEPLOYMENT

## Server (Linux, systemd)

`scripts/install_systemd.sh` is provided to write a systemd unit file
referencing the user-provided path.  A minimal unit:

```ini
[Unit]
Description=TRADE WITH ARUN signal engine
After=network-online.target

[Service]
Type=simple
User=twa
WorkingDirectory=/opt/trade_with_arun
EnvironmentFile=/opt/trade_with_arun/.env
ExecStart=/opt/trade_with_arun/.venv/bin/twa run
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now twa.service
sudo journalctl -u twa.service -f
```

## Background noise budget

The orchestrator's worst-case CPU is `O(adapter_count × symbols)`.  With
the default watchlist (3 symbols, 3 exchanges), one cycle idempotently
costs ~9 HTTP calls and < 100 ms CPU on a modest VPS.

## Network egress
Roughly ~25 KB / cycle.  Telegram-based posting is rate-limited to
`TWA_TELEGRAM_MIN_INTERVAL_S`.

## Health
* `data_dir/heartbeat.json` is rewritten every `TWA_HEARTBEAT_S`.
* `data_dir/signals.jsonl` is appended on every published signal.

Both files can be harvested by Prometheus / Loki / Vector / fluent-bit.
