# RISK_ENGINE

## Risk contract
The engine is *advisory only* — it never opens, modifies, or closes
any position.  All decisions are recorded as `RiskVerdict.accepted`
flags.

## Decisions

### Cooldowns
Per `(symbol, timeframe, side)`.  Once a signal is published, the next
candidates for the same key are silently rejected for `TWA_RISK_COOLDOWN_S`
seconds (default 900s = 15 minutes).

### Confidence capping
The maximum published confidence is `TWA_RISK_MAX_CONFIDENCE` (0.95
by default).

### Regime dampeners
* `STRESSED` regime → cap absolute confidence at **0.35**.
* `high_volatility` (realised_vol ≥ 0.85) → multiply by **0.75**.
* `news_dampen` (from NewsGuard) → multiply.
* `ml_calibration` (from Calibrator) → multiply.

### Exposure protection
`RiskEngine.active_ids` caps at 5 simultaneous active signals
(default).

### Calibrated threshold
A signal is *rejected* when `calibrated_conf < 0.20`.

### Adaptive stops
The signal engine emits ATR-based invalidation levels (default
`±1.5 ATR` for invalidation, `±0.5 ATR` for entry zone, `1×/2×/3×` for
targets).  These are *advisory* — placed by the user, not by us.

## Outputs

The Telegram message includes:
* entry zone low/high,
* targets (1R / 2R / 3R),
* invalidation,
* expected edge in bps,
* news dampen factor,
* top-5 factor contributions.

## Why we do not provide leverage / position sizing

Position sizing is a *user-level* decision.  The user's broker, fee
model, portfolio context, risk limits, and tax regime are unknowable
from our side.  We deliver the **cleanest possible signal** and let
the user decide *how much* to allocate.
