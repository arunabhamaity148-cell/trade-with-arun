"""Shared research utilities."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Iterable, List

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from twa.config import Settings
from twa.models.types import Timeframe, coerce_timeframe

BAR_SECONDS = {
    Timeframe.M1: 60,
    Timeframe.M5: 300,
    Timeframe.M15: 900,
    Timeframe.H1: 3600,
    Timeframe.H4: 14400,
    Timeframe.D1: 86400,
}


def ensure_research_dir(settings: Settings, *parts: str) -> Path:
    path = settings.data_dir / "research"
    for part in parts:
        path = path / part
    path.mkdir(parents=True, exist_ok=True)
    return path


def estimate_bar_count(start: datetime, end: datetime, timeframe: Timeframe | str, padding: int = 8) -> int:
    tf = coerce_timeframe(timeframe)
    seconds = max((end - start).total_seconds(), 0.0)
    return max(50, int(np.ceil(seconds / BAR_SECONDS[tf])) + padding)


def forward_returns(close: pd.Series, horizon: int) -> pd.Series:
    return close.shift(-horizon) / close - 1.0


def rank_ic(feature: pd.Series, target: pd.Series) -> float:
    valid = pd.concat([feature, target], axis=1).dropna()
    if len(valid) < 8:
        return 0.0
    corr = spearmanr(valid.iloc[:, 0], valid.iloc[:, 1]).correlation
    return 0.0 if corr is None or np.isnan(corr) else float(corr)


def sharpe_like(returns: Iterable[float]) -> float:
    arr = np.asarray(list(returns), dtype=float)
    if len(arr) < 2:
        return 0.0
    sd = arr.std(ddof=1)
    if sd == 0:
        return 0.0
    return float(arr.mean() / sd * np.sqrt(len(arr)))


def max_drawdown(returns: Iterable[float]) -> float:
    arr = np.asarray(list(returns), dtype=float)
    if arr.size == 0:
        return 0.0
    equity = np.cumsum(arr)
    peaks = np.maximum.accumulate(equity)
    drawdowns = equity - peaks
    return float(drawdowns.min())


def content_hash(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha1(encoded).hexdigest()


def split_slices(length: int, parts: int) -> List[slice]:
    if length <= 0 or parts <= 0:
        return []
    bounds = np.linspace(0, length, parts + 1, dtype=int)
    return [slice(int(bounds[i]), int(bounds[i + 1])) for i in range(parts) if bounds[i + 1] > bounds[i]]


def benjamini_hochberg(p_values: Iterable[float]) -> List[float]:
    values = [1.0 if v is None or np.isnan(v) else float(max(0.0, min(1.0, v))) for v in p_values]
    if not values:
        return []
    order = np.argsort(values)
    ranked = np.asarray(values, dtype=float)[order]
    q_values = np.empty(len(values), dtype=float)
    prev = 1.0
    for idx in range(len(values) - 1, -1, -1):
        rank = idx + 1
        adjusted = min(prev, ranked[idx] * len(values) / rank)
        q_values[order[idx]] = adjusted
        prev = adjusted
    return [float(v) for v in q_values]


def population_stability_index(baseline: pd.Series, recent: pd.Series, bins: int = 10) -> float:
    left = baseline.dropna().to_numpy(dtype=float)
    right = recent.dropna().to_numpy(dtype=float)
    if left.size < bins or right.size < bins:
        return 0.0
    quantiles = np.unique(np.quantile(left, np.linspace(0.0, 1.0, bins + 1)))
    if len(quantiles) < 3:
        return 0.0
    expected, _ = np.histogram(left, bins=quantiles)
    actual, _ = np.histogram(right, bins=quantiles)
    expected = np.clip(expected / max(expected.sum(), 1), 1e-6, None)
    actual = np.clip(actual / max(actual.sum(), 1), 1e-6, None)
    return float(np.sum((actual - expected) * np.log(actual / expected)))


def load_jsonl(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return pd.DataFrame(rows)
