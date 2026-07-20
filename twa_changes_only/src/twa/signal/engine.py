"""Signal engine (mathematically consistent multi-factor scoring).

Design
------
A multi-factor score is computed as:

    score = Σ_i ( w_i(regime) · Φ_i(feat_i) )

where Φ : R → [-1, +1] is a factor-specific normaliser calibrated so raw
magnitudes from different features are comparable. `compute_signal()` now
emits the *raw* score-derived confidence only; News Guard dampening and ML
calibration are applied exactly once downstream in `twa.risk.engine`.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import numpy as np

from twa.config import Settings
from twa.features.engineering import FEATURE_CATALOGUE, candles_to_frame, compute_all
from twa.logging import get_logger
from twa.models.types import (
    Candle,
    FactorContribution,
    RegimeLabel,
    Side,
    SignalEntryState,
    SignalIdea,
    SignalLifecycleState,
    Timeframe,
)
from twa.regime.classifier import assign_weights

log = get_logger("signal")


LEGACY_FACTOR_KEYS = [
    "funding",
    "basis",
    "oi_delta",
    "trend_strength_48",
    "log_return_16",
    "obv_slope_48",
    "volume_zscore_96",
    "realised_vol_30",
    "obi",
]

# Directional scoring keys after v2.6 factor-pruning. The removed features remain
# available to regime/risk/research code, but they no longer push score sign.
FACTOR_KEYS = [
    "funding",
    "basis",
    "oi_delta",
    "trend_strength_48",
    "log_return_16",
    "obi",
]


_FACTOR_SCALES: Dict[str, tuple[str, float]] = {
    "funding": ("linear", 1.0),
    "basis": ("tanh", 0.015),
    "oi_delta": ("linear", 1.0),
    "obi": ("linear", 1.0),
    "trend_strength_48": ("tanh", 0.75),
    "log_return_16": ("tanh", 0.05),
    "obv_slope_48": ("signed_log", 400.0),
    "volume_zscore_96": ("tanh", 2.5),
    "realised_vol_30": ("tanh", 1.6),
}


def atr(df_high: np.ndarray, df_low: np.ndarray, df_close: np.ndarray, n: int = 14) -> float:
    """Average True Range."""
    if len(df_high) < n + 1:
        return float(np.mean(df_high - df_low))
    h = df_high[-n - 1 :]
    l = df_low[-n - 1 :]
    c = df_close[-n - 1 :]
    tr = np.maximum.reduce(
        [
            h - l,
            np.abs(h - np.concatenate([[c[0]], c[:-1]])),
            np.abs(l - np.concatenate([[c[0]], c[:-1]])),
        ]
    )
    return float(np.mean(tr))


def normalise_factor(name: str, raw: float) -> float:
    """Map raw feature value → [-1, +1] on empirically comparable scales."""
    if raw is None or (isinstance(raw, float) and math.isnan(raw)):
        return 0.0
    value = float(raw)
    mode, scale = _FACTOR_SCALES.get(name, ("linear", 1.0))
    scale = max(scale, 1e-9)
    if mode == "linear":
        mapped = value / scale
    elif mode == "tanh":
        mapped = math.tanh(value / scale)
    elif mode == "signed_log":
        mapped = math.copysign(min(1.0, math.log1p(abs(value)) / math.log1p(scale)), value)
    else:
        mapped = value
    return float(max(-1.0, min(1.0, mapped)))


@dataclass(frozen=True)
class EngineConfig:
    min_confidence: float = 0.20
    score_to_conf_K: float = 0.35
    edge_bps_per_unit_score: float = 25.0
    risk_reward_targets: tuple = (1.5, 3.0, 4.5)
    entry_zone_atr: float = 0.5
    invalidation_atr: float = 1.5
    expiry_bars_multiplier: float = 0.75
    fair_value_ema_span: int = 20
    fair_value_gap_wait_atr: float = 0.35
    fair_value_confirm_band_atr: float = 0.10
    sniper_max_wait_bars: int = 4


DEFAULT_CFG = EngineConfig()


def engine_config_from_settings(settings: Settings, **overrides: float | int | None) -> EngineConfig:
    """Project runtime Settings into the signal-engine config surface.

    Several operational sniper controls live in `Settings` but the signal engine
    previously ignored them and always ran with the hard-coded `DEFAULT_CFG`.
    That made live/paper/backtest/research disagree with the operator's config.
    """
    cfg = replace(
        DEFAULT_CFG,
        fair_value_gap_wait_atr=float(settings.sniper_fair_value_band_atr),
        fair_value_confirm_band_atr=float(settings.sniper_confirmation_close_band_atr),
        sniper_max_wait_bars=int(settings.sniper_max_wait_bars),
    )
    clean = {key: value for key, value in overrides.items() if value is not None and hasattr(cfg, key)}
    return replace(cfg, **clean) if clean else cfg


def project_symbol_factors(
    funding_norm: float,
    basis_norm: float,
    oi_delta_norm: float,
    obi_norm: float,
) -> Dict[str, float]:
    """Return only the cross-exchange overrides.

    Candle-derived factors are built separately; returning placeholders here
    risks accidentally zeroing them out when the dict is merged.
    """
    return {
        "funding": float(funding_norm),
        "basis": float(basis_norm),
        "oi_delta": float(oi_delta_norm),
        "obi": float(obi_norm),
    }


def build_factor_vector(features: Dict[str, float]) -> Dict[str, float]:
    """Build the full feature snapshot used by scoring/research/risk.

    Not every returned key is necessarily scored directionally. `FACTOR_KEYS`
    defines the active directional vector; `LEGACY_FACTOR_KEYS` is retained so
    the research harness can re-run historical ablations against the old stack.
    """
    return {
        "trend_strength_48": features.get("trend_strength_48", 0.0),
        "log_return_16": features.get("log_return_16", 0.0),
        "obv_slope_48": features.get("obv_slope_48", 0.0),
        "volume_zscore_96": features.get("volume_zscore_96", 0.0),
        "realised_vol_30": features.get("realised_vol_30", 0.0),
        "funding": 0.0,
        "basis": 0.0,
        "oi_delta": 0.0,
        "obi": 0.0,
    }


def compute_signal(
    candles: List[Candle],
    timeframe: Timeframe,
    factor_overrides: Dict[str, float],
    regime: RegimeLabel,
    regime_conf: float,
    cfg: EngineConfig = DEFAULT_CFG,
    news_dampen: float = 1.0,
    ml_calibration: float = 1.0,
    score_factor_keys: Optional[List[str]] = None,
) -> Optional[SignalIdea]:
    """Compute a raw SignalIdea candidate or None if below threshold.

    `news_dampen` and `ml_calibration` are accepted for backward compatibility
    but are not applied here. They are recorded and consumed once in the risk
    engine so the confidence pipeline remains single-application and auditable.
    """
    del news_dampen, ml_calibration
    score_keys = list(score_factor_keys or FACTOR_KEYS)
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
    for name in score_keys:
        if name not in factors:
            continue
        norm = normalise_factor(name, factors[name])
        w = float(weights.get(name, 0.0))
        c = w * norm
        score += c
        contribs.append(
            FactorContribution(
                name=name,
                raw_value=float(factors[name]),
                norm_value=norm,
                weight=w,
                contribution=c,
                rationale=_explain(name, norm, factors[name]),
            )
        )

    raw_confidence = float(max(0.0, min(0.99, math.tanh(abs(score) / cfg.score_to_conf_K) * regime_conf)))
    if raw_confidence < cfg.min_confidence:
        log.debug("signal.below_min_confidence", score=round(score, 3), conf=round(raw_confidence, 3))
        return None

    side = Side.LONG if score >= 0 else Side.SHORT
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

    fair_value = _fair_value(df, span=cfg.fair_value_ema_span)
    fair_value_gap_atr = ((last_close - fair_value) / max(a, 1e-9)) * (1.0 if side == Side.LONG else -1.0)
    entry_state, entry_trigger = _sniper_entry_state(
        side,
        last_close,
        fair_value,
        a,
        cfg.fair_value_gap_wait_atr,
        cfg.fair_value_confirm_band_atr,
    )

    rationale.append(f"Regime {regime.value} (regime confidence {regime_conf:.2f}).")
    rationale.append(f"Raw score {score:+.3f} → raw confidence {raw_confidence:.2f} before news/ML/risk gating.")
    rationale.append(
        f"ATR geometry uses invalidation {cfg.invalidation_atr:.2f} ATR and targets "
        f"{cfg.risk_reward_targets[0]:.1f}/{cfg.risk_reward_targets[1]:.1f}/{cfg.risk_reward_targets[2]:.1f} ATR."
    )
    if entry_state == SignalEntryState.WAIT:
        rationale.append(
            f"Sniper wait: price is extended {fair_value_gap_atr:+.2f} ATR from fair value; wait for pullback/confirmation."
        )
    else:
        rationale.append(f"Sniper entry ready: {entry_trigger}.")

    expected_edge_bps = score * cfg.edge_bps_per_unit_score
    sig_id = hashlib.sha1(f"{candles[-1].symbol}|{candles[-1].open_time}|{round(score, 4)}".encode()).hexdigest()[:12]

    return SignalIdea(
        id=sig_id,
        symbol=candles[-1].symbol,
        exchange=candles[-1].exchange,
        timeframe=timeframe,
        side=side,
        regime=regime,
        confidence=raw_confidence,
        raw_confidence=raw_confidence,
        ml_calibration=1.0,
        final_confidence=None,
        expected_edge_bps=expected_edge_bps,
        entry_zone=[round(entry_lo, 6), round(entry_hi, 6)],
        targets=[round(t, 6) for t in targets],
        invalidation=round(invalidation, 6),
        rationale=rationale,
        factor_contributions=contribs,
        news_dampen=1.0,
        basis=float(factors.get("basis", 0.0)),
        oi_delta=float(factors.get("oi_delta", 0.0)),
        fair_value=round(fair_value, 6),
        fair_value_gap_atr=round(float(fair_value_gap_atr), 4),
        entry_state=entry_state,
        entry_trigger=entry_trigger,
        max_wait_bars=cfg.sniper_max_wait_bars,
        lifecycle_state=SignalLifecycleState.DETECTED,
        expires_at=datetime.now(tz=timezone.utc) + _expiry_delta(timeframe, cfg.expiry_bars_multiplier),
    )


def _fair_value(df, span: int = 20) -> float:
    close = df["close"].to_numpy(dtype=float)
    volume = np.maximum(df["volume"].to_numpy(dtype=float), 1e-9)
    typical = (df["high"].to_numpy(dtype=float) + df["low"].to_numpy(dtype=float) + close) / 3.0
    vwap = float(np.sum(typical[-span:] * volume[-span:]) / np.sum(volume[-span:])) if len(df) >= 2 else float(close[-1])
    ema = float(df["close"].ewm(span=min(span, max(2, len(df))), adjust=False).mean().iloc[-1])
    return float((vwap + ema) / 2.0)


def _sniper_entry_state(
    side: Side,
    last_close: float,
    fair_value: float,
    atr_value: float,
    wait_atr: float,
    confirm_band_atr: float,
) -> tuple[SignalEntryState, str]:
    gap = ((last_close - fair_value) / max(atr_value, 1e-9)) * (1.0 if side == Side.LONG else -1.0)
    if gap > wait_atr:
        return SignalEntryState.WAIT, "extended_from_fair_value"
    if abs(last_close - fair_value) <= confirm_band_atr * max(atr_value, 1e-9):
        return SignalEntryState.ENTER_NOW, "fair_value_retest"
    return SignalEntryState.ENTER_NOW, "close_confirmation"


def _expiry_delta(timeframe: Timeframe, multiplier: float) -> timedelta:
    seconds = {
        Timeframe.M1: 60,
        Timeframe.M5: 300,
        Timeframe.M15: 900,
        Timeframe.H1: 3600,
        Timeframe.H4: 14_400,
        Timeframe.D1: 86_400,
    }[timeframe]
    return timedelta(seconds=max(60, int(seconds * max(0.25, multiplier))))


def _explain(factor: str, norm: float, raw: float) -> str:
    direction = "BULLISH" if norm > 0.05 else ("BEARISH" if norm < -0.05 else "NEUTRAL")
    mapping = {
        "trend_strength_48": "trend strength (corr-style)",
        "log_return_16": "medium-term log return",
        "obv_slope_48": "OBV accumulation/distribution slope",
        "volume_zscore_96": "volume burst z-score",
        "realised_vol_30": "annualised realised vol",
        "funding": "funding rate (perps crowd positioning)",
        "basis": "spot-perp basis deviation",
        "oi_delta": "open-interest change momentum",
        "obi": "orderbook bid-ask imbalance",
    }
    return f"{direction} ({mapping.get(factor, factor)}, raw={raw:.4g})"
