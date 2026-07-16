# ENGINEERING_DECISIONS

> Every decision is documented with *why* — never *just because*.

## Why a deterministic rule-based regime classifier (not an HMM)

Academic literature (Figà-Talamanca et al., 2021; Malekinezhad, 2026)
shows HMM-based regime detection works well for crypto. We deliberately
ship the rule-based classifier as the **primary** path because:

1. **Explainability**: every classification is a check of well-named
   thresholds; an auditor can reproduce it.
2. **No black-box drift**: an ML model can silently degrade.
3. **Predictable cost**: classification is O(1) per cycle.

The `RegimeDetector` class still supports HMM via scikit-learn if the
operator provides a pre-trained model.

## Why multi-factor scoring instead of single ML model

Crypto microstructure literature (Ackerer et al., 2024; Ackerer / Jermann) and
empirical funding-rate predictability studies (SSRN 5576424, 2025) point
to **funding** and **OI deltas** as *statistically meaningful*, with
**order-book imbalance** carrying strong predictive power (Anastasopoulos,
forthcoming). Other indicators — classic RSI / MACD strategies — have
replicated weaknesses in crypto markets (PMC9920669). We therefore
*avoid* using RSI / MACD as standalone factors; trend *strength* is taken
as a standardised correlation-style metric over 48 bars instead. Each
factor is documented in `FEATURE_ENGINEERING.md` with formula, regime
interaction and failure modes.

> Decision: ship **explainable multi-factor weighted scoring**;
> reserve ML for a **calibrator** layer that *adjusts* confidence after
> the engine has emitted a candidate.  A `note: ml.identity_fallback`
> branch logs when the calibrator is unavailable, so users can audit.

## Why signal-only (no order placement)

The product is named `TRADE WITH ARUN`.  It is explicitly described in
`README.md` and every Telegram message as a **signal engine**, not an
execution engine.  Reasons:

1. **Compliance**: many jurisdictions restrict retail-facing automated
   order placement; a signal product keeps the operator in control.
2. **Operational risk**: a runaway aggregation bug could otherwise place
   unbounded orders.  We avoid the entire class of bugs.
3. **Honesty**: we never know the user's exchange, fees, position sizing
   preferences or counterparty risk limits.

The architecture, documentation, and CLI banner are unambiguous about
this constraint.

## Why a single-process async architecture (not microservices)

Operational footprint is critical — fewer moving parts means fewer
failure modes.  The engine is single-binary, async, fault-tolerant,
restartable from `twa run`.  The stateful subsystems (health, cooldown)
are intentionally *in-process*: they would lose state across a restart
and that is acceptable for a signal product.

## Decision log

| Date (UTC) | Decision | Followed by code |
|------------|----------|------------------|
| 2024-Q4 | Use only free public data | `src/twa/data/*` |
| 2024-Q4 | Never place orders | `src/twa/cli/main.py`, `src/twa/telegram/bot.py` |
| 2024-Q4 | Deterministic regime classifier primary | `src/twa/regime/classifier.py` |
| 2024-Q4 | ML calibrator optional, transparent fallback | `src/twa/ml/calibrator.py` |
| 2024-Q4 | ATR-based stops only | `src/twa/signal/engine.py` |
| 2024-Q4 | Backtest must NEVER fabricate numbers | `src/twa/backtest/replay.py` |
