# TRADE WITH ARUN v2.5 — production audit summary

## Scope completed
- Part A duplicate-row bug fix with regression coverage.
- Part B signal-pipeline instrumentation and gate candidate comparison on accessible live public data.
- Part C repo audit fixes for runtime config wiring, lifecycle/risk-slot release, restart restoration, breakeven logic, Telegram admin context, and config redaction.

## Part A — duplicate-row root cause
The two ablation rows were hitting the same practical path because `production_engine_technical_only` and `production_engine_without_news_guard` both called the production benchmark with `news_dampen=1.0`, while neither variant removed nor differentiated cross-exchange overrides inside the benchmark path. In addition, the old benchmark implementation never exercised sniper activation or active-signal release, so multiple rows could collapse onto the same sparse output profile even when their labels implied different configurations.

### Fix
- Added explicit `ProductionVariant` dispatch in `src/twa/research/benchmarking.py`.
- `technical_only=True` now zeroes cross-exchange overrides.
- Full-factor variants now source cross-exchange overrides from available research-session snapshots.
- Added regression coverage proving:
  1. technical-only vs full-factor rows diverge when factor availability differs;
  2. with-news-guard vs without-news-guard diverge when news dampening changes acceptance.

## Part B — signal starvation breakdown
See `reports/production_audit_metrics.json`.

### Environment fallback used for the live run
This sandbox could fetch Coinbase hourly candles, but Binance/Bybit public derivatives endpoints were blocked here (451/403). The code-path audit and regression tests are still valid, but the live comparison file therefore uses accessible public candles plus whatever session snapshots were available.

### Legacy starved path (bug-compatible reproduction)
- Trades: 5
- Edge/trade: -21.33 bps
- Hit rate: 20.0%
- Drawdown: 120.85 bps
- Sharpe-like: -0.755
- Rejection counts: realized 5, risk max_active_signals_reached 79, risk calibrated_confidence_below_threshold 6, signal_below_min_confidence 30

### Fixed current gates
- Trades: 32
- Edge/trade: -55.50 bps
- Hit rate: 28.1%
- Drawdown: 1802.01 bps
- Sharpe-like: -4.778
- Rejection counts: realized 32, sniper_wait_timeout 41, risk max_active_signals_reached 11, risk calibrated_confidence_below_threshold 6, signal_below_min_confidence 30

### Candidate loosening checks
1. `min_confidence=0.17`
   - Trades: 32
   - No realized-trade increase versus fixed current gates.
   - Rejections simply moved from `signal_below_min_confidence` into downstream `risk_calibrated_confidence_below_threshold`.
   - Net result: no useful improvement.

2. `sniper_entry=False`
   - Trades: 62
   - Edge/trade: -33.91 bps
   - Hit rate: 40.3%
   - Drawdown: 2270.87 bps
   - Sharpe-like: -3.812
   - This increases sample size well beyond the requested 30–50 range, but it is not a deployable fix because expectancy is still negative and the sample expansion comes from bypassing the fair-value confirmation gate entirely.

### Decision for Part B
The dominant bottleneck in the starved result was **not** genuine alpha scarcity. It was a harness/state bug: accepted signals were never being released, so `max_active_signals_reached` choked the path after the first 5 acceptances. After fixing that, the default gate stack already produced 32 realized trades in the accessible walk-forward run, which clears the minimum-sample objective without indiscriminately loosening every gate.

## Part C — repo audit findings

### Fixed in this pass
1. **Benchmark variant dispatch bug** — ablation labels now map to distinct configurations.
2. **Benchmark signal-state leak** — production walk-forward benchmarking now tracks realized trades, sniper wait timeouts, and active-slot release instead of leaking `max_active` forever.
3. **Runtime config wiring bug** — sniper-related `Settings` values were previously ignored by the signal engine. They are now projected into `EngineConfig` consistently across CLI/live/research paths.
4. **Live lifecycle risk-slot leak** — terminal lifecycle transitions and stale candidates now release risk slots instead of permanently consuming active capacity.
5. **Restart state loss** — lifecycle manager now restores open candidates/active signals from SQLite on startup.
6. **Breakeven stop reference bug** — TP1 now moves invalidation to the entry-zone midpoint approximation instead of the lower bound, which previously under-protected LONG signals and mis-handled SHORT semantics.
7. **Config secret exposure** — CLI config output now redacts bot token/chat ID/CryptoPanic key.
8. **Telegram admin context wiring** — orchestrator now keeps bot admin views populated with recent signals, health snapshot, and redacted config.
9. **Regression coverage expansion** — added tests for variant divergence, news-guard acceptance divergence, lifecycle release on terminal transitions, and restart restoration of waiting candidates.

### Unresolved blockers (explicit)
1. **Historical cross-exchange factors are still not truly point-in-time in research.**
   - The research session still only has current/static snapshots for funding/OI/orderbook unless the caller injects historical values.
   - That means full-factor historical ablations are still not institutionally honest enough for serious capital allocation.
   - Required follow-up: build/store a point-in-time historical microstructure dataset for funding, basis, OI delta, and OBI.

2. **This sandbox could not reproduce the user's exact derivatives-data environment.**
   - Binance/Bybit public endpoints were blocked here.
   - The attached live metrics file therefore validates the code path on accessible public candles, but not on the user's exact original feed mix.
   - Required follow-up: rerun the same report in an unrestricted environment against the full derivatives feeds.

3. **The accessible live walk-forward sample is still negative expectancy after the fixes.**
   - The code is less wrong now, but the sampled edge is still negative.
   - Required follow-up: do not optimize blindly; first collect a point-in-time derivatives dataset and re-run honest walk-forward comparisons before tuning factors or thresholds.

## Test status
- Baseline suite before changes: 84/84 passing tests.
- Suite after changes: 88/88 passing tests.
