"""Market regime classifier.

The previous v2.2 regime stack mixed two different concepts:

1. *Regime classification* — what environment the market is in.
2. *Directional scoring* — whether the signal should lean long or short.

Several factor weights in the v2.2 table encoded directional sign directly
(e.g. negative weights inside ``TREND_DOWN``), even though the underlying
features are already signed. That double-inverted bearish features and could
turn obviously down-trending windows into bullish scores. The same table also
let unsigned features such as realised volatility and volume z-score push the
score's sign, which creates a structural bullish bias because those features
are almost always positive.

This module keeps the deterministic five-regime classifier, but the weight
matrix is now *direction-neutral*: weights express feature usefulness, while
feature sign determines long vs short direction. Unsigned features remain
valuable for classification and risk, but no longer dictate signal direction.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

from twa.logging import get_logger
from twa.models.types import RegimeLabel

log = get_logger("regime")


@dataclass(frozen=True)
class RegimeConfig:
    vol_volatile: float = 0.95
    vol_stressed: float = 1.55
    vol_range_max: float = 0.65
    range_trend_max: float = 0.18
    range_strong: float = 0.18
    trend_confirm: float = 0.28
    trend_strong: float = 0.55
    return_trend_confirm: float = 0.012
    return_trend_strong: float = 0.03
    relative_range_chop: float = 0.018
    kurt_stressed: float = 6.0


DEFAULT_CONFIG = RegimeConfig()

# Factors whose raw value already contains directional sign.
SIGNED_FACTORS = {
    "funding",
    "basis",
    "oi_delta",
    "trend_strength_48",
    "log_return_16",
    "obv_slope_48",
    "obi",
}

# These are useful for regime detection / risk modulation, but are not
# direction-bearing by themselves. Giving them directional score weight creates
# a persistent bias because they are usually non-negative.
NON_DIRECTIONAL_FACTORS = {
    "volume_zscore_96",
    "realised_vol_30",
}


FACTOR_WEIGHTS: Dict[RegimeLabel, Dict[str, float]] = {
    RegimeLabel.TREND_UP: {
        "funding": 0.08,
        "basis": 0.08,
        "oi_delta": 0.12,
        "trend_strength_48": 0.30,
        "log_return_16": 0.18,
        "obv_slope_48": 0.12,
        "volume_zscore_96": 0.0,
        "realised_vol_30": 0.0,
        "obi": 0.12,
    },
    # IMPORTANT: signed factors keep positive usefulness weights here. Their raw
    # values become negative in downtrends, so the score naturally turns bearish.
    RegimeLabel.TREND_DOWN: {
        "funding": 0.08,
        "basis": 0.08,
        "oi_delta": 0.12,
        "trend_strength_48": 0.30,
        "log_return_16": 0.18,
        "obv_slope_48": 0.12,
        "volume_zscore_96": 0.0,
        "realised_vol_30": 0.0,
        "obi": 0.12,
    },
    RegimeLabel.RANGE: {
        "funding": 0.18,
        "basis": 0.14,
        "oi_delta": 0.12,
        "trend_strength_48": 0.08,
        "log_return_16": 0.06,
        "obv_slope_48": 0.10,
        "volume_zscore_96": 0.0,
        "realised_vol_30": 0.0,
        "obi": 0.22,
    },
    RegimeLabel.VOLATILE: {
        "funding": 0.12,
        "basis": 0.12,
        "oi_delta": 0.14,
        "trend_strength_48": 0.22,
        "log_return_16": 0.14,
        "obv_slope_48": 0.10,
        "volume_zscore_96": 0.0,
        "realised_vol_30": 0.0,
        "obi": 0.16,
    },
    RegimeLabel.STRESSED: {
        "funding": 0.10,
        "basis": 0.10,
        "oi_delta": 0.12,
        "trend_strength_48": 0.24,
        "log_return_16": 0.16,
        "obv_slope_48": 0.10,
        "volume_zscore_96": 0.0,
        "realised_vol_30": 0.0,
        "obi": 0.12,
    },
}


def _normalise_weights(d: Dict[str, float]) -> Dict[str, float]:
    s = sum(abs(v) for v in d.values())
    if s == 0:
        return {k: 0.0 for k in d}
    return {k: float(v / s) for k, v in d.items()}


WEIGHTS_NORMALISED: Dict[RegimeLabel, Dict[str, float]] = {r: _normalise_weights(w) for r, w in FACTOR_WEIGHTS.items()}


def classify(features: Dict[str, float], cfg: RegimeConfig = DEFAULT_CONFIG) -> RegimeLabel:
    """Deterministic classifier with non-degenerate thresholds."""
    vol = abs(features.get("realised_vol_30", 0.0))
    kurt = abs(features.get("return_kurt_64", 0.0))
    trend = float(features.get("trend_strength_48", 0.0))
    rng = abs(float(features.get("relative_range_48", 0.0)))
    ret = float(features.get("log_return_16", 0.0))
    ret_score = max(-1.0, min(1.0, ret / cfg.return_trend_strong))
    directional_score = 0.70 * trend + 0.30 * ret_score

    if vol >= cfg.vol_stressed or kurt >= cfg.kurt_stressed or (vol >= 1.20 and abs(ret) >= 0.04):
        return RegimeLabel.STRESSED
    if vol >= cfg.vol_volatile or (rng >= cfg.relative_range_chop * 1.35 and abs(trend) >= cfg.trend_confirm):
        return RegimeLabel.VOLATILE
    range_threshold = min(cfg.range_trend_max, cfg.range_strong)
    if (
        vol <= cfg.vol_range_max
        and abs(trend) <= range_threshold
        and abs(ret) <= cfg.return_trend_confirm
        and rng <= cfg.relative_range_chop
    ):
        return RegimeLabel.RANGE
    if directional_score >= cfg.trend_confirm and (trend >= cfg.trend_confirm or ret >= cfg.return_trend_confirm):
        return RegimeLabel.TREND_UP
    if directional_score <= -cfg.trend_confirm and (trend <= -cfg.trend_confirm or ret <= -cfg.return_trend_confirm):
        return RegimeLabel.TREND_DOWN
    if vol <= cfg.vol_range_max * 1.1 and abs(trend) <= range_threshold * 1.3:
        return RegimeLabel.RANGE
    return RegimeLabel.TREND_UP if directional_score >= 0 else RegimeLabel.TREND_DOWN


def regime_confidence(features: Dict[str, float], regime: RegimeLabel, cfg: RegimeConfig = DEFAULT_CONFIG) -> float:
    """How decisive the classification was (0..1)."""
    vol = abs(features.get("realised_vol_30", 0.0))
    trend = float(features.get("trend_strength_48", 0.0))
    ret = float(features.get("log_return_16", 0.0))
    rng = abs(float(features.get("relative_range_48", 0.0)))
    ret_score = min(1.0, abs(ret) / max(cfg.return_trend_strong, 1e-9))

    if regime in (RegimeLabel.TREND_UP, RegimeLabel.TREND_DOWN):
        score = min(1.0, 0.65 * abs(trend) + 0.35 * ret_score)
    elif regime == RegimeLabel.RANGE:
        range_threshold = min(cfg.range_trend_max, cfg.range_strong)
        score = min(
            1.0,
            max(0.0, 1.0 - vol / max(cfg.vol_range_max, 1e-9)) * 0.7
            + max(0.0, 1.0 - abs(trend) / max(range_threshold, 1e-9)) * 0.3,
        )
    elif regime == RegimeLabel.VOLATILE:
        score = min(1.0, max(vol / cfg.vol_volatile, rng / max(cfg.relative_range_chop, 1e-9)))
    else:
        score = min(1.0, max(vol / cfg.vol_stressed, abs(features.get("return_kurt_64", 0.0)) / max(cfg.kurt_stressed, 1e-9)))
    return max(0.1, min(0.95, float(score)))


def assign_weights(regime: RegimeLabel) -> Dict[str, float]:
    return dict(WEIGHTS_NORMALISED[regime])
