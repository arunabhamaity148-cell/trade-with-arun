"""Signal engine (mathematically consistent multi-factor scoring).

Design
------
A multi-factor score is computed as:

    score = Σ_i ( w_i(regime) · Φ_i(feat_i) )
    where Φ : R → [-1, +1] is the feature's normalised value
    and w_i are the regime-dependent weights from `regime.classifier`.

Confidence is then derived:
    conf = tanh( |score| / K ) normalised by regime confidence and dampened by
          News Guard and ML calibrator (see `twa.ml.calibrator`).

Side, entry zone, targets, and invalidation are computed from the
multi-factor score combined with ATR-based volatility gating.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import numpy as np

from twa.logging import get_logger
from twa.models.types import (
    Candle, FactorContribution, RegimeLabel, Side, SignalIdea, Timeframe,
)
from twa.regime.classifier import assign_weights, regime_confidence
from twa.features.engineering import (
    FEATURE_CATALOGUE, candles_to_frame, compute_all,
)

log = get_logger("signal")


# Map external factor names → entries in the engine's projected dict.
FACTOR_KEYS = [
    "funding", "basis", "oi_delta", "trend_strength_48", "log_return_16",
    "obv_slope_48", "volume_zscore_96", "realised_vol_30", "obi",
]


def atr(df_high: np.ndarray, df_low: np.ndarray, df_close: np.ndarray, n: int = 14) -> float:
    """Average True Range."""
    if len(df_high) < n + 1:
        return float(np.mean(df_high - df_low))
    h = df_high[-n - 1:]
    l = df_low[-n - 1:]
    c = df_close[-n - 1:]
    tr = np.maximum.reduce([h - l, np.abs(h - np.concatenate([[c[0]], c[:-1]])),
                            np.abs(l - np.concatenate([[c[0]], c[:-1]]))])
    return float(np.mean(tr))


def normalise_factor(name: str, raw: float) -> float:
    """Map raw feature value → [-1, +1]."""
    if raw is None or (isinstance(raw, float) and math.isnan(raw)):
        return 0.0
    if name in FEATURE_CATALOGUE:
        # crude, deterministic mapping; preserved as a documented heuristic.
        return max(-1.0, min(1.0, float(raw)))
    # External / non-catalog features: clip on a known scale.
    clip_map = {
        "funding":      1.0,
        "basis":        0.05,
        "oi_delta":     1.0,
        "obi":          1.0,
    }
    band = clip_map.get(name, 1.0)
    return max(-1.0, min(1.0, float(raw) / band))


@dataclass(frozen=True)
class EngineConfig:
    min_confidence: float = 0.05
    score_to_conf_K: float = 0.35   # tanh score/confidence scaling
    edge_bps_per_unit_score: float = 25.0
    risk_reward_targets: tuple = (1.0, 2.0, 3.0)
    entry_zone_atr: float = 0.5
    invalidation_atr: float = 1.5


DEFAULT_CFG = EngineConfig()


def project_symbol_factors(
    funding_norm: float,
    basis_norm: float,
    oi_delta_norm: float,
    obi_norm: float,
) -> Dict[str, float]:
    """Form the 9-key factor vector; OHLCV-derived ones default to 0."""
    return {
        "funding": float(funding_norm),
        "basis":   float(basis_norm),
        "oi_delta": float(oi_delta_norm),
        "obi": float(obi_norm),
        # Note: 5 of 9 factors derived from candles/feature-engineering pipeline
        # will overwrite the placeholders below via `build_factor_vector`.
        "trend_strength_48": 0.0,
        "log_return_16": 0.0,
        "obv_slope_48": 0.0,
        "volume_zscore_96": 0.0,
        "realised_vol_30": 0.0,
    }


def build_factor_vector(features: Dict[str, float]) -> Dict[str, float]:
    """Build the canonical 9-key factor vector from feature snapshot."""
    return {
        "trend_strength_48": features.get("trend_strength_48", 0.0),
        "log_return_16":     features.get("log_return_16", 0.0),
        "obv_slope_48":      features.get("obv_slope_48", 0.0),
        "volume_zscore_96":  features.get("volume_zscore_96", 0.0),
        "realised_vol_30":   features.get("realised_vol_30", 0.0),
        # placeholders for cross-exchange — caller fills in below
        "funding": 0.0, "basis": 0.0, "oi_delta": 0.0, "obi": 0.0,
    }


def compute_signal(
    candles: List[Candle],
    timeframe: Timeframe,
    factor_overrides: Dict[str, float],     # funding/basis/oi_delta/obi from xchg
    regime: RegimeLabel,
    regime_conf: float,
    cfg: EngineConfig = DEFAULT_CFG,
    news_dampen: float = 1.0,
    ml_calibration: float = 1.0,
) -> Optional[SignalIdea]:
    """Compute a SignalIdea (or None if below minimum threshold)."""
    if not candles or len(candles) < 30:
        return None

    df = candles_to_frame(candles)
    if df.empty:
        return None

    features = compute_all(candles)
    factors = build_factor_vector(features)
    factors.update(factor_overrides)

    weights = assign_weights(regime)

    contribs: List[FactorContribution] = []
    score = 0.0
    rationale: List[str] = []
    for name in FACTOR_KEYS:
        if name not in factors:
            continue
        norm = normalise_factor(name, factors[name])
        w = float(weights.get(name, 0.0))
        c = w * norm
        score += c
        contribs.append(FactorContribution(
            name=name, raw_value=float(factors[name]),
            norm_value=norm, weight=w, contribution=c,
            rationale=_explain(name, norm, factors[name]),
        ))

    base_conf = math.tanh(abs(score) / cfg.score_to_conf_K) * regime_conf
    confidence = float(max(0.0, min(0.99,
        base_conf * max(0.1, news_dampen) * max(0.1, ml_calibration))))
    if confidence < cfg.min_confidence:
        log.debug("signal.below_min_confidence", score=round(score, 3),
                  conf=round(confidence, 3))
        return None

    if score >= 0:
        side = Side.LONG
    elif score < 0:
        side = Side.SHORT
    else:
        side = Side.NEUTRAL

    last_close = float(df["close"].iloc[-1])
    a = atr(df["high"].to_numpy(), df["low"].to_numpy(), df["close"].to_numpy(), n=14)
    atr_pct = a / max(last_close, 1e-9)

    entry_lo = last_close * (1 - cfg.entry_zone_atr * atr_pct)
    entry_hi = last_close * (1 + cfg.entry_zone_atr * atr_pct)
    if side == Side.LONG:
        invalidation = last_close * (1 - cfg.invalidation_atr * atr_pct)
        targets = [last_close * (1 + rr * atr_pct) for rr in cfg.risk_reward_targets]
    else:
        invalidation = last_close * (1 + cfg.invalidation_atr * atr_pct)
        targets = [last_close * (1 - rr * atr_pct) for rr in cfg.risk_reward_targets]

    rationale.append(f"Regime {regime.value} (regime confidence {regime_conf:.2f}).")
    rationale.append(f"Score {score:+.3f} → confidence {confidence:.2f}.")
    rationale.append(f"ATR-based entry/invalidation around close {last_close:.4f}.")

    expected_edge_bps = (score * cfg.edge_bps_per_unit_score) * float(news_dampen)

    sig_id = hashlib.sha1(
        f"{candles[-1].symbol}|{candles[-1].open_time}|{round(score, 4)}".encode()
    ).hexdigest()[:12]

    return SignalIdea(
        id=sig_id,
        symbol=candles[-1].symbol,
        exchange=candles[-1].exchange,
        timeframe=timeframe,
        side=side,
        regime=regime,
        confidence=confidence,
        expected_edge_bps=expected_edge_bps,
        entry_zone=[round(entry_lo, 6), round(entry_hi, 6)],
        targets=[round(t, 6) for t in targets],
        invalidation=round(invalidation, 6),
        rationale=rationale,
        factor_contributions=contribs,
        news_dampen=news_dampen,
        expires_at=datetime.now(tz=timezone.utc) + timedelta(minutes=15),
    )


def _explain(factor: str, norm: float, raw: float) -> str:
    direction = "BULLISH" if norm > 0.05 else ("BEARISH" if norm < -0.05 else "NEUTRAL")
    mapping = {
        "trend_strength_48": "trend strength (corr-style)",
        "log_return_16": "medium-term log return",
        "obv_slope_48": "OBV accumulation/distribution slope",
        "volume_zscore_96": "volume burst z-score",
        "realised_vol_30": "annualised realised vol",
        "funding": "funding rate (perps crowd positioning)",
        "basis":   "spot-perp basis deviation",
        "oi_delta": "open-interest change momentum",
        "obi": "orderbook bid-ask imbalance",
    }
    return f"{direction} ({mapping.get(factor, factor)}, raw={raw:.4g})"
