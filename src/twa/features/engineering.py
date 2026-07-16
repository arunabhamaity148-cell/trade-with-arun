"""Professional feature engineering.

All features are PURE (numpy/pandas) and operate on a list of `Candle`
objects.  Each feature returns a `numpy.float64` scalar that can be
consumed by the regime classifier, signal engine, and ML calibrator.

The feature list is the *output* of `twa.features.catalog.list_features()`
and is documented in `docs/FEATURE_ENGINEERING.md`.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Callable, Dict, List, Optional

import numpy as np
import pandas as pd

from twa.logging import get_logger
from twa.models.types import Candle

log = get_logger("features")


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def candles_to_frame(candles: List[Candle]) -> pd.DataFrame:
    """Vectorised candle → OHLCV dataframe sorted by time ascending."""
    if not candles:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    df = pd.DataFrame([{
        "open_time": c.open_time,
        "open": c.open,
        "high": c.high,
        "low": c.low,
        "close": c.close,
        "volume": c.volume,
    } for c in candles])
    df = df.sort_values("open_time").reset_index(drop=True)
    return df[["open", "high", "low", "close", "volume"]]


def realised_vol(closes: np.ndarray, window: int = 30) -> float:
    """Annualised realised volatility (Cox-Ingersoll-Ross style log-return std)."""
    if len(closes) < window + 1:
        return float("nan")
    logret = np.diff(np.log(closes[-window - 1:]))
    return float(np.std(logret, ddof=1) * math.sqrt(365 * 24 * 4))  # 15-min calendar scaling


def rolling_zscore(x: np.ndarray, window: int = 96) -> float:
    """Z-score of the latest value within a rolling window — emphasises extremes."""
    if len(x) < window:
        return float("nan")
    s = x[-window:]
    mu, sd = float(np.mean(s)), float(np.std(s, ddof=1))
    if sd == 0:
        return 0.0
    return float((x[-1] - mu) / sd)


# -----------------------------------------------------------------------------
# Feature primitives
# -----------------------------------------------------------------------------
@dataclass(frozen=True)
class FeatureDef:
    name: str
    fn: Callable[[pd.DataFrame], float]
    purpose: str
    formula: str
    regime_dependent: bool = True
    weight_default: float = 1.0


def f_log_return(df: pd.DataFrame, n: int = 16) -> float:
    if len(df) < n + 1:
        return 0.0
    return float(np.log(df["close"].iloc[-1] / df["close"].iloc[-1 - n]))


def f_realised_vol(df: pd.DataFrame) -> float:
    closes = df["close"].to_numpy(dtype=float)
    return realised_vol(closes, window=min(30, len(closes) - 1))


def f_volume_zscore(df: pd.DataFrame) -> float:
    vol = df["volume"].to_numpy(dtype=float)
    return rolling_zscore(vol, window=min(96, len(vol)))


def f_trend_strength(df: pd.DataFrame) -> float:
    """Linear-regression slope normalised by mean price → in [-1, 1] for trending series."""
    closes = df["close"].to_numpy(dtype=float)
    n = min(48, len(closes))
    if n < 8:
        return 0.0
    y = closes[-n:]
    x = np.arange(n, dtype=float)
    x = (x - x.mean()) / (x.std() or 1.0)
    y = (y - y.mean()) / (y.std() or 1.0)
    slope = float(np.dot(x, y) / n)  # correlation coeff (slope of standardised data)
    return max(-1.0, min(1.0, slope))


def f_relative_range(df: pd.DataFrame) -> float:
    """Parkinson-style range normalised by close. High in chop, low in trend."""
    h = df["high"].to_numpy(dtype=float)
    lo = df["low"].to_numpy(dtype=float)
    c = df["close"].to_numpy(dtype=float)
    n = min(48, len(h))
    if n < 4:
        return 0.0
    rng = (h[-n:] - lo[-n:]) / np.maximum(c[-n:], 1e-9)
    return float(np.mean(rng))


def f_obv_slope(df: pd.DataFrame) -> float:
    """Slope of on-balance volume — proxy for accumulation/distribution pressure."""
    if len(df) < 24:
        return 0.0
    close = df["close"].to_numpy(dtype=float)
    vol = df["volume"].to_numpy(dtype=float)
    direction = np.sign(np.diff(close, prepend=close[0]))
    obv = np.cumsum(direction * vol)
    n = min(48, len(obv))
    if n < 4:
        return 0.0
    s = obv[-n:]
    x = np.arange(n, dtype=float)
    return float(np.polyfit(x, s, 1)[0])  # raw slope; engine normalises further


def f_skewness(df: pd.DataFrame) -> float:
    """Return skewness — asymmetry of recent returns."""
    closes = df["close"].to_numpy(dtype=float)
    n = min(64, len(closes))
    if n < 8:
        return 0.0
    rets = np.diff(np.log(closes[-n:]))
    if rets.std() == 0:
        return 0.0
    return float(pd.Series(rets).skew())


def f_kurtosis(df: pd.DataFrame) -> float:
    closes = df["close"].to_numpy(dtype=float)
    n = min(64, len(closes))
    if n < 8:
        return 0.0
    rets = np.diff(np.log(closes[-n:]))
    if rets.std() == 0:
        return 0.0
    return float(pd.Series(rets).kurtosis())


# Catalogue ------------------------------------------------------------------
FEATURE_CATALOGUE: Dict[str, FeatureDef] = {
    "log_return_16": FeatureDef(
        "log_return_16", lambda df: f_log_return(df, 16),
        purpose="Captures medium-term directional bias (16 bars).",
        formula="log(C_t / C_{t-16})",
        weight_default=0.8,
    ),
    "realised_vol_30": FeatureDef(
        "realised_vol_30", f_realised_vol,
        purpose="Annualised vol — feeds risk engine and regime classifier.",
        formula="std(log returns, 30) * sqrt(annualisation)",
        weight_default=0.6,
    ),
    "volume_zscore_96": FeatureDef(
        "volume_zscore_96", f_volume_zscore,
        purpose="Identifies volume bursts (often precede directional moves).",
        formula="(V_t - μ) / σ over 96 bars",
        weight_default=0.7,
    ),
    "trend_strength_48": FeatureDef(
        "trend_strength_48", f_trend_strength,
        purpose="Correlation-style trendiness in [-1, 1].",
        formula="corr(close, time) over 48 bars",
        weight_default=0.9,
    ),
    "relative_range_48": FeatureDef(
        "relative_range_48", f_relative_range,
        purpose="High in range/chop, low in trending regimes.",
        formula="mean((H - L) / C) over 48 bars",
        weight_default=0.4,
    ),
    "obv_slope_48": FeatureDef(
        "obv_slope_48", f_obv_slope,
        purpose="Order-flow proxy — accumulation/distribution pressure.",
        formula="polyfit(OBV, t) over 48 bars",
        weight_default=0.7,
    ),
    "return_skew_64": FeatureDef(
        "return_skew_64", f_skewness,
        purpose="Asymmetry — positive skew → upside tail.",
        formula="skew(log returns, 64 bars)",
        weight_default=0.3,
    ),
    "return_kurt_64": FeatureDef(
        "return_kurt_64", f_kurtosis,
        purpose="Tail risk — high kurtosis → stress / liquidation risk.",
        formula="kurtosis(log returns, 64 bars)",
        weight_default=0.3,
    ),
}


def list_features() -> List[str]:
    return list(FEATURE_CATALOGUE.keys())


def compute_all(candles: List[Candle]) -> Dict[str, float]:
    """Return named feature values for a candle list, with NaN replaced by 0.0."""
    df = candles_to_frame(candles)
    if df.empty:
        return {name: 0.0 for name in FEATURE_CATALOGUE}
    out: Dict[str, float] = {}
    for name, feat in FEATURE_CATALOGUE.items():
        try:
            v = float(feat.fn(df))
        except Exception:  # noqa: BLE001
            v = float("nan")
        if v != v:  # NaN guard
            v = 0.0
        out[name] = v
    return out
