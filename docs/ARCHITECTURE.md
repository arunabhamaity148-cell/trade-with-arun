# ARCHITECTURE

> Single-process, async-first, modular.

## High-level diagram

```
                ┌─────────────────┐
                │   CLI / `twa`   │
                └────────┬────────┘
                         │
                         ▼
                ┌─────────────────┐
                │  Orchestrator   │   ← single async loop
                └──┬──┬──┬──┬──┬──┘
                   │  │  │  │  │
   ┌───────────────┘  │  │  │  └───────────────┐
   │  ┌───────────────┘  │  └───────────────┐  │
   ▼  ▼                  ▼                  ▼  ▼
┌──────┐  ┌──────┐  ┌──────────┐  ┌──────┐  ┌────────┐
│ Data │  │News  │  │ Features │  │Risk  │  │Telegram│
│Agg.  │  │Guard │  │  + Reg.  │  │Engine│  │  Bot   │
└──┬───┘  └──┬───┘  └────┬─────┘  └──┬───┘  └────┬───┘
   │         │            │           │           │
   ▼         ▼            ▼           ▼           ▼
Exchanges   RSS /     Compute all   Cooldowns,  Telegram
(HTTP/WS)   Crypto-   features,     exposure,    Chat
            Panic     classify,     dampeners,
                      score signal  confidence
                                  calibration

                 ┌─────────────────────────┐
                 │ Monitoring: heartbeat,  │
                 │   CPU/RSS/feed health   │
                 └─────────────────────────┘
```

## Data flow (one cycle)

1. **Orchestrator** awaits each `interval_s` seconds.
2. `MarketDataAggregator.fetch_candles()` is called on every watchlist
   symbol; adapters are queried in parallel; healthy feed wins;
   cross-exchange dispersion is verified.
3. Cross-exchange factors (funding, OI delta, OBI) are fetched in parallel.
4. **News Guard** refreshes once per `news_refresh_s`.
5. **Feature engineering** turns OHLCV into the 8-feature catalogue.
6. **Regime classifier** decides the active regime.
7. **Signal engine** computes a 9-factor score, applies a regime-specific
   weighting, derives confidence, builds a `SignalIdea` with entry /
   targets / invalidation.
8. **Risk engine** checks cooldowns, exposure, news dampening, ML
   calibration; either accepts or rejects.
9. **Telegram** receives an explainable Markdown message (if enabled).
10. **Health monitor** writes a heartbeat document and updates state.

## Design principles

* **Async everywhere.** No thread-blocking code anywhere in the runtime.
* **Typed.** Every boundary is a Pydantic model.
* **Pure compute where possible.** Feature engineering never mutates
  external state and is trivially testable.
* **Config-driven, not code-driven.** Every tunable weight, threshold, or
  refresh interval is exposed via `TWA_*` env vars.
* **Fail loudly, recover silently for transient errors.** Network blips
  never crash the loop; persistent issues are surfaced via health.

## Where behaviour is documented

| Concern | Doc |
|--------|------|
| Feature formulas | `FEATURE_ENGINEERING.md` |
| Multi-factor engine math | `SIGNAL_ENGINE.md` |
| Regime / weights table | `SIGNAL_ENGINE.md` |
| Risk decisions | `RISK_ENGINE.md` |
| News Guard keyword list | `NEWS_GUARD.md` |
| Data sources & endpoints | `DATA_PIPELINE.md` |
| Config keys | `CONFIG_REFERENCE.md` |
| Install / run / deploy | `INSTALL.md`, `DEPLOYMENT.md`, `OPERATIONS.md` |
| Tests | `TESTING.md` |
| Public CLI surface | `API_REFERENCE.md` |
| Why / why not | `ENGINEERING_DECISIONS.md` |
| System internals (State, queues, errors) | `SYSTEM_DESIGN.md` |
