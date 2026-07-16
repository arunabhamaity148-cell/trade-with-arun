# CONFIG_REFERENCE

> Every value can be overridden via environment variable.
> A `.env` template is shipped as `.env.example`.

## General

| Var | Default | Description |
|-----|---------|-------------|
| `TWA_ENV` | `paper` | `paper`, `live` or `test` (no auth ever required) |
| `TWA_LOG_LEVEL` | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `TWA_DATA_DIR` | `./data` | persistent directory |
| `TWA_TIMEZONE` | `UTC` | informational |

## Symbols / timeframe

| Var | Default | Description |
|-----|---------|-------------|
| `TWA_SYMBOLS` | `BTCUSDT,ETHUSDT,SOLUSDT` | CSV of watchlist symbols |
| `TWA_TIMEFRAME` | `1h` | one of `1m, 5m, 15m, 1h, 4h, 1d` |
| `TWA_LOOKBACK_BARS` | `500` | bars pulled per cycle (50 ≤ n ≤ 5000) |

## Exchanges

| Var | Default |
|-----|---------|
| `TWA_EXCHANGES` | `binance,bybit,coinbase` |
| `TWA_HTTP_TIMEOUT_S` | `15` |
| `TWA_HTTP_CONCURRENCY` | `8` |
| `TWA_WS_ENABLED` | `true` (reserved) |

## News

| Var | Default |
|-----|---------|
| `TWA_NEWS_ENABLED` | `true` |
| `TWA_NEWS_REFRESH_S` | `180` |
| `TWA_NEWS_SOURCES` | `cryptopanic,rss` |
| `TWA_CRYPTOPANIC_PUBLIC_KEY` | *(empty)* |

## Telegram

| Var | Default |
|-----|---------|
| `TWA_TELEGRAM_ENABLED` | `false` |
| `TWA_TELEGRAM_BOT_TOKEN` | *(empty)* |
| `TWA_TELEGRAM_CHAT_ID` | *(empty)* |
| `TWA_TELEGRAM_MIN_INTERVAL_S` | `120` |

## ML

| Var | Default |
|-----|---------|
| `TWA_ML_ENABLED` | `false` |
| `TWA_ML_MODEL_PATH` | `./models/calibrator.joblib` |

## Monitoring

| Var | Default |
|-----|---------|
| `TWA_HEARTBEAT_S` | `30` |
| `TWA_METRICS_PORT` | `9100` (reserved) |

## Risk

| Var | Default |
|-----|---------|
| `TWA_RISK_MAX_CONFIDENCE` | `0.95` |
| `TWA_RISK_NEWS_DAMPEN` | `0.5` (reserved for future tuning) |
| `TWA_RISK_COOLDOWN_S` | `900` |
