"""Market regime classifier.

Approach
--------
A *robust, deterministic* rule-based classifier (no ML required).  At each
cycle, given the latest feature snapshot and price action context, we
classify the regime into one of:

    TREND_UP, TREND_DOWN, RANGE, VOLATILE, STRESSED

The classifier emits:
    * a label                         (RegimeLabel)
    * a confidence ∈ [0, 1]           based on how decisively each rule fires
    * a recommended factor weights    dict (used by the signal engine)

Academic motivation:
    HMM-based regime detection works well for crypto (Figà-Talamanca 2021;
    Malekinezhad 2026), but a deterministic rule-based classifier is
    *explainable* and *auditable* for a production signal engine, which is
    what this product promises.  The thresholds are derived from typical
    crypto realised-vol distributions across 1H/4H bars — documented in
    `docs/SIGNAL_ENGINE.md`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

import numpy as np

from twa.logging import get_logger
from twa.models.types import RegimeLabel
from twa.features.engineering import (
    FEATURE_CATALOGUE, compute_all, candles_to_frame,
)

log = get_logger("regime")


@dataclass(frozen=True)
class RegimeConfig:
    # volatility thresholds (annualised)
    vol_volatile: float = 0.85     # ≥ → volatile
    vol_stressed: float = 1.30     # ≥ → stressed
    vol_range_max: float = 0.45    # ≤ → quiet/range candidate

    # range-vs-trend thresholds (unitless, in [0,1])
    trend_strong: float = 0.55     # ≥ → strong trend
    range_strong: float = 0.20     # ≤ → strong range

    # kurtosis threshold for stress
    kurt_stressed: float = 6.0


DEFAULT_CONFIG = RegimeConfig()


# factor weights vary per regime. Total always sums to 1.0.
FACTOR_WEIGHTS: Dict[RegimeLabel, Dict[str, float]] = {
    RegimeLabel.TREND_UP: {
        "funding":      0.05,
        "basis":        0.05,
        "oi_delta":     0.10,
        "trend_strength_48":  0.30,
        "log_return_16":      0.15,
        "obv_slope_48":       0.10,
        "volume_zscore_96":   0.10,
        "realised_vol_30":    0.05,
        "obi":               0.10,
    },
    RegimeLabel.TREND_DOWN: {
        "funding":      0.05,
        "basis":        0.05,
        "oi_delta":     0.10,
        "trend_strength_48":  -0.30,  # negative weight: trend-down rewards negative slope
        "log_return_16":      -0.15,
        "obv_slope_48":       -0.10,
        "volume_zscore_96":   0.10,
        "realised_vol_30":    0.05,
        "obi":               -0.10,
    },
    RegimeLabel.RANGE: {
        "funding":      0.20,
        "basis":        0.15,
        "oi_delta":     0.15,
        "trend_strength_48":  0.05,
        "log_return_16":      0.05,
        "obv_slope_48":       0.10,
        "volume_zscore_96":   0.05,
        "realised_vol_30":    -0.05,  # negative: vol is bad in a range
        "obi":               0.25,
    },
    RegimeLabel.VOLATILE: {
        "funding":      0.10,
        "basis":        0.15,
        "oi_delta":     0.20,
        "trend_strength_48":  0.10,
        "log_return_16":      0.05,
        "obv_slope_48":       0.05,
        "volume_zscore_96":   0.20,
        "realised_vol_30":    -0.10,
        "obi":               0.15,
    },
    RegimeLabel.STRESSED: {
        "funding":      -0.10,
        "basis":        -0.10,
        "oi_delta":     -0.15,
        "trend_strength_48":  0.0,
        "log_return_16":      0.0,
        "obv_slope_48":       0.0,
        "volume_zscore_96":   0.10,
        "realised_vol_30":    -0.25,
        "obi":               -0.05,
    },
}


def _normalise_weights(d: Dict[str, float]) -> Dict[str, float]:
    s = sum(abs(v) for v in d.values())
    if s == 0:
        return {k: 0.0 for k in d}
    return {k: float(v / s) for k, v in d.items()}


WEIGHTS_NORMALISED: Dict[RegimeLabel, Dict[str, float]] = {
    r: _normalise_weights(w) for r, w in FACTOR_WEIGHTS.items()
}


def classify(features: Dict[str, float], cfg: RegimeConfig = DEFAULT_CONFIG) -> RegimeLabel:
    """Deterministic regime classifier.

    Inputs:
      - features: complete output of `compute_all`
    Returns: RegimeLabel (one of 5)
    """
    vol = abs(features.get("realised_vol_30", 0.0))
    kurt = abs(features.get("return_kurt_64", 0.0))
    trend = features.get("trend_strength_48", 0.0)
    rng = features.get("relative_range_48", 0.0)
    ret = features.get("log_return_16", 0.0)

    if vol >= cfg.vol_stressed or kurt >= cfg.kurt_stressed:
        return RegimeLabel.STRESSED
    if vol >= cfg.vol_volatile:
        return RegimeLabel.VOLATILE
    if vol <= cfg.vol_range_max and abs(trend) <= cfg.range_strong:
        return RegimeLabel.RANGE
    if trend >= cfg.trend_strong or ret > 0:
        return RegimeLabel.TREND_UP
    if trend <= -cfg.trend_strong or ret < 0:
        return RegimeLabel.TREND_DOWN
    return RegimeLabel.RANGE


def regime_confidence(features: Dict[str, float], regime: RegimeLabel,
                      cfg: RegimeConfig = DEFAULT_CONFIG) -> float:
    """How decisive the classification was (0..1).  More decisive = higher."""
    vol = abs(features.get("realised_vol_30", 0.0))
    trend = features.get("trend_strength_48", 0.0)
    score = 0.0
    if regime in (RegimeLabel.TREND_UP, RegimeLabel.TREND_DOWN):
        score = abs(trend)
    elif regime == RegimeLabel.RANGE:
        score = 1.0 - min(1.0, vol / max(cfg.vol_range_max, 1e-9))
    elif regime == RegimeLabel.VOLATILE:
        score = min(1.0, vol / cfg.vol_volatile)
    elif regime == RegimeLabel.STRESSED:
        score = min(1.0, vol / cfg.vol_stressed)
    return max(0.1, min(0.95, float(score)))


def assign_weights(regime: RegimeLabel) -> Dict[str, float]:
    return dict(WEIGHTS_NORMALISED[regime])
