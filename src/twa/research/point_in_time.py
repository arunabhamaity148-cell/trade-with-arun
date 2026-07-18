"""Point-in-time feature-store discipline for research datasets."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Dict, Iterable, List

import pandas as pd

from twa.features.engineering import FEATURE_CATALOGUE, compute_all
from twa.models.types import Candle, Timeframe, coerce_timeframe
from twa.regime.classifier import classify
from twa.research.utils import BAR_SECONDS


@dataclass(frozen=True)
class FeatureAvailability:
    name: str
    source: str
    availability_lag_bars: int = 1
    description: str = "Known at the close of the source bar."


FEATURE_AVAILABILITY: Dict[str, FeatureAvailability] = {
    name: FeatureAvailability(name=name, source="ohlcv", availability_lag_bars=1)
    for name in FEATURE_CATALOGUE
}


def bar_timedelta(timeframe: Timeframe | str) -> timedelta:
    tf = coerce_timeframe(timeframe)
    return timedelta(seconds=BAR_SECONDS[tf])


def build_point_in_time_feature_frame(symbol: str, timeframe: Timeframe | str, candles: List[Candle], min_history: int = 64) -> pd.DataFrame:
    tf = coerce_timeframe(timeframe)
    rows: List[dict] = []
    if not candles:
        return pd.DataFrame(columns=["timestamp", "availability_time", "symbol", "close", "regime"])
    delta = bar_timedelta(tf)
    for idx in range(min_history - 1, len(candles)):
        window = candles[: idx + 1]
        feats = compute_all(window)
        row = {
            "timestamp": candles[idx].open_time,
            "availability_time": candles[idx].open_time + delta,
            "symbol": symbol,
            "open": candles[idx].open,
            "high": candles[idx].high,
            "low": candles[idx].low,
            "close": candles[idx].close,
            "volume": candles[idx].volume,
            "regime": classify(feats).value,
        }
        row.update(feats)
        rows.append(row)
    return pd.DataFrame(rows)


def feature_store_manifest() -> pd.DataFrame:
    rows = [
        {
            "feature": meta.name,
            "source": meta.source,
            "availability_lag_bars": meta.availability_lag_bars,
            "description": meta.description,
        }
        for meta in FEATURE_AVAILABILITY.values()
    ]
    return pd.DataFrame(rows).sort_values("feature").reset_index(drop=True)


def assert_future_data_does_not_move_past_features(
    symbol: str,
    timeframe: Timeframe | str,
    candles: List[Candle],
    *,
    cutoff_index: int,
    mutate: callable,
    min_history: int = 64,
) -> bool:
    """Leakage guard: mutating future candles must not change past features."""
    original = build_point_in_time_feature_frame(symbol, timeframe, candles, min_history=min_history)
    mutated = list(candles)
    mutated[cutoff_index:] = mutate(mutated[cutoff_index:])
    changed = build_point_in_time_feature_frame(symbol, timeframe, mutated, min_history=min_history)
    past_end = max(0, cutoff_index - min_history)
    left = original.iloc[:past_end].reset_index(drop=True)
    right = changed.iloc[:past_end].reset_index(drop=True)
    if len(left) != len(right):
        return False
    return left.equals(right)
