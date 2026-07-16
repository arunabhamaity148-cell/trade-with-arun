# FEATURE_ENGINEERING

> Eight engineered features, each documented with purpose, formula,
> regime interaction, failure modes, and importance.

| # | Name | Purpose | Formula | Regime interaction | Failure modes | Importance |
|---|------|---------|---------|--------------------|---------------|------------|
| 1 | `log_return_16` | captures medium-term directional bias | `log(C_t / C_{t-16})` | ↑ in trend regimes; suppressed in range/stressed | chop | high |
| 2 | `realised_vol_30` | feeds the risk & regime engines | `std(log returns, 30 bars) × √annualisation` | ↑ in volatile/stressed; dampens confidence | illiquid windows → false flat | high |
| 3 | `volume_zscore_96` | detects bursts that precede directional moves | `(V_t - μ_96) / σ_96` | ↑ everywhere except STRESSED (where it scales confidence) | spoofing / wash | medium |
| 4 | `trend_strength_48` | corr-style trendiness | `corr(close, t) over 48 bars` | ↑ in trend regimes; flipping is the regime classifier | look-ahead bias; smoothed through rolling window | high |
| 5 | `relative_range_48` | chop detector | `mean((H-L)/C) over 48 bars` | ↑ in RANGE; ↓ in trend | high wick candles confuse | medium |
| 6 | `obv_slope_48` | accumulation/distribution pressure | `polyfit(OBV, t) over 48 bars` | aligns with trend | low volume underestimates | medium |
| 7 | `return_skew_64` | asymmetry tail | `skew(log R, 64 bars)` | reward positive skew in TREND_UP; punish negative skew in TREND_DOWN | rare events dominate | low–medium |
| 8 | `return_kurt_64` | tail risk | `kurtosis(log R, 64 bars)` | REJECT in STRESSED ≥ 6 | small N ⇒ noisy | low–medium |

## Why **not** RSI / MACD

The published literature (PMC9920669, Mahajan 2015, Zatwarnicki 2023)
suggests:

* Optimised RSI/MACD may beat buy-and-hold *only* for very specific
  parameterisations (often in-sample).
* Several empirical replications in crypto show neither indicator
  outperforms buy-and-hold out-of-sample.

We therefore reject RSI, MACD, Stochastic, and Bollinger Bands as
*standalone* factors.  We retain `trend_strength_48` (a robust
correlation-based proxy of trend) and `relative_range_48` (a robust chop
detector) which capture the *substantive* information these indicators
attempt to encode.

## What about funding rate / OI / OBI?

These are *cross-exchange derivatives* features — see
`src/twa/features/cross_exchange.py`.  They are documented separately:

| Name | Range | Source | Importance |
|------|-------|--------|------------|
| `funding` (normalised ±0.05%) | [-1, +1] | Binance/Bybit perp funding | high (academic evidence, SSRN 5576424) |
| `oi_delta` | [-1, +1] | Binance/Bybit OI history | high |
| `obi` (best-N imbalance) | [-1, +1] | L2 orderbook | high (Anastasopoulos 2024/26) |
| `basis` (spot-perp deviation) | [-1, +1] | reserved (no consolidated free feed) | reserved for paid feed integration |

> Funding rates, OI momentum, and OBI are the most empirically
> meaningful microstructure features in the literature we reviewed.
> **Every OHLCV feature above is also testable in isolation.**

## Normalisation

Every feature is mapped via `twa.signal.engine.normalise_factor`.
Catalogue features use a deterministic tanh-style mapper:
`max(-1, min(1, raw_value))`.  Cross-exchange features clip on a known
band (e.g. `funding` → ±0.0005).

## Failure modes

All feature primitives return `0.0` (a documented neutral value) on
arbitrary exceptions.  The orchestrator never trips on a corrupt
input — failure is silenced at the boundary and the orchestrator
issues an `orchestrator.symbol_failed` log line.
