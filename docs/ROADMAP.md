# ROADMAP (v1.0)

> This document is a planning artifact.  All milestones map to deliverables
> already shipped in v1.0 of `TRADE WITH ARUN`.  No roadmap promises are
> pending — every “✓” below corresponds to working code that ships today.

| Milestone | Status | Where |
|-----------|--------|-------|
| M1: typed config + structured logging | ✅ | `src/twa/config.py`, `src/twa/logging.py` |
| M2: free public data adapters (Binance/Bybit/Coinbase) | ✅ | `src/twa/data/` |
| M3: failover + cross-exchange dispersion guard | ✅ | `src/twa/data/cache.py` |
| M4: feature engineering catalog (8 features) | ✅ | `src/twa/features/engineering.py` |
| M5: regime classifier (5 regimes) | ✅ | `src/twa/regime/classifier.py` |
| M6: multi-factor signal engine | ✅ | `src/twa/signal/engine.py` |
| M7: risk engine (cooldowns, exposure, dampeners) | ✅ | `src/twa/risk/engine.py` |
| M8: news guard (RSS + optional CryptoPanic) | ✅ | `src/twa/news/guard.py` |
| M9: ML calibrator (transparent fallback) | ✅ | `src/twa/ml/calibrator.py` |
| M10: backtest (simulate + Monte Carlo, honest) | ✅ | `src/twa/backtest/replay.py` |
| M11: Telegram premium UX + commands | ✅ | `src/twa/telegram/bot.py` |
| M12: monitoring & heartbeat | ✅ | `src/twa/monitoring/health.py` |
| M13: orchestrator end-to-end | ✅ | `src/twa/orchestration/engine.py` |
| M14: CLI (`twa run|paper|backtest|signals|health|config`) | ✅ | `src/twa/cli/main.py` |
| M15: test suite (config, models, features, regime, signal, risk, news, backtest, telegram, ml, data, integration) | ✅ | `tests/` |
| M16: documentation matching implementation | ✅ | `docs/` |
| M17: production-grade packaging (ZIP) | ✅ | `scripts/build_zip.sh` |

## Things explicitly OUT of scope for v1.0
* Order placement, exchange auth, live trading — the product is signal-only.
* Strategy backtests against held-out data — the engine ships the harness;
  the user is expected to perform their own honest out-of-sample validation
  before relying on any reported number.
* Cloud / SaaS / multi-tenant dashboards — out of scope.
