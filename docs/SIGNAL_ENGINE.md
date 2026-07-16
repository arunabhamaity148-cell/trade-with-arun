# SIGNAL_ENGINE

> Mathematically consistent multi-factor scoring.

## Score formula

```
score = Σ_i  w_i(regime) · Φ_i(feature_i)
```

* `Φ` maps each feature into `[-1, +1]`.
* `w_i(regime)` is a regime-dependent weight (see table below). Absolute
  weights sum to 1 within each regime, so the score lives in `[-1, +1]`.
* Confidence is derived via:

```
raw_conf = tanh(|score| / K) · regime_confidence
calibrated_conf = raw_conf · news_dampen · ml_calibration
```

* `K = 1.0` (default; configurable in `EngineConfig`).
* `regime_confidence ∈ [0.1, 0.95]`.
* `news_dampen ∈ [0.1, 1.0]` (set by `NewsGuard.dampen_for`).
* `ml_calibration ∈ [0.05, 0.99]` or `1.0` (identity fallback).

A signal is **published** only when `calibrated_conf ≥ min_confidence`
(default 0.20).

## Side / entry / invalidation

* `side = LONG` if `score ≥ 0`, else `SHORT`, otherwise `NEUTRAL`.
* Entry zone = `last_close ± entry_zone_atr × ATR%`.
* Invalidation = `last_close ∓ invalidation_atr × ATR%` (consistent with side).
* Targets at 1R / 2R / 3R × ATR% (configurable in `EngineConfig`).
* Each `SignalIdea` carries full human-readable **rationale** and
  per-factor **FactorContribution** records.

## Regime weights (the canonical table)

```
                          TREND_UP  TREND_DOWN  RANGE  VOLATILE  STRESSED
funding                     0.05      0.05       0.20     0.10     -0.10
basis                       0.05      0.05       0.15     0.15     -0.10
oi_delta                    0.10      0.10       0.15     0.20     -0.15
trend_strength_48           0.30     -0.30       0.05     0.10      0.00
log_return_16               0.15     -0.15       0.05     0.05      0.00
obv_slope_48                0.10     -0.10       0.10     0.05      0.00
volume_zscore_96            0.10      0.10       0.05     0.20      0.10
realised_vol_30             0.05      0.05      -0.05    -0.10     -0.25
obi                         0.10     -0.10       0.25     0.15     -0.05
```

Each regime row is Norm-1 — that's not arbitrary: it makes scores
*comparable across regimes* and prevents regime-specific biases.

## Conflict resolution

* Negative weights (e.g. trend strength in TREND_DOWN) effectively
  *invert* a factor's contribution.  This is intentional — the same
  data carries opposite meaning in opposite regimes.
* All contributions are exposed via `SignalIdea.factor_contributions`
  so users can audit dominance, balance, and any conflict in
  Telegram messages.

## No magic numbers

Every constant is exposed either via `EngineConfig` or via env
variables (`TWA_RISK_*`, `TWA_TIMEFRAME`, etc.).  No constant is buried
inside an expression without a documentation line above it.
