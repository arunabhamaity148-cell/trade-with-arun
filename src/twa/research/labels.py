"""As-of outcome labelling detached from the backtest simulator."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, List, Optional

import pandas as pd

from twa.backtest.replay import _first_target_hit
from twa.models.types import Candle, Side, Timeframe


@dataclass(frozen=True)
class SignalGeometry:
    entry_time: datetime
    entry_price: float
    side: Side
    invalidation: float
    targets: List[float]
    max_horizon_bars: int = 16


@dataclass(frozen=True)
class OutcomeLabel:
    label: str
    target_index: int
    resolved_at: Optional[datetime]
    resolution_bars: int
    exit_price: Optional[float]


@dataclass(frozen=True)
class LabelSummary:
    label: str
    target_index: int
    resolved_at: Optional[datetime]
    resolution_bars: int
    exit_price: Optional[float]
    outcome_sign: int


def label_signal_outcome(geometry: SignalGeometry, future: Iterable[Candle]) -> OutcomeLabel:
    """Resolve which target / stop was hit first using only post-entry data."""
    future_bars = list(future)[: max(1, int(geometry.max_horizon_bars))]
    if not future_bars:
        return OutcomeLabel(label="no_data", target_index=0, resolved_at=None, resolution_bars=0, exit_price=None)
    direction = 1 if geometry.side == Side.LONG else -1
    for idx, bar in enumerate(future_bars, start=1):
        stop_hit = (direction == 1 and bar.low <= geometry.invalidation) or (direction == -1 and bar.high >= geometry.invalidation)
        target_hit = _first_target_hit(geometry.targets, bar, direction, 1)
        if stop_hit and target_hit is not None:
            return OutcomeLabel("stop_first", 0, bar.open_time, idx, geometry.invalidation)
        if target_hit is not None:
            target_idx, target_price = target_hit
            return OutcomeLabel(f"target_{target_idx}", target_idx, bar.open_time, idx, target_price)
        if stop_hit:
            return OutcomeLabel("stop", 0, bar.open_time, idx, geometry.invalidation)
    return OutcomeLabel("horizon", 0, future_bars[-1].open_time, len(future_bars), float(future_bars[-1].close))


def summarize_outcome(label: OutcomeLabel) -> LabelSummary:
    sign = 1 if label.label.startswith("target_") else (-1 if label.label in {"stop", "stop_first"} else 0)
    return LabelSummary(
        label=label.label,
        target_index=label.target_index,
        resolved_at=label.resolved_at,
        resolution_bars=label.resolution_bars,
        exit_price=label.exit_price,
        outcome_sign=sign,
    )


def build_outcome_frame(records: List[dict]) -> pd.DataFrame:
    frame = pd.DataFrame(records)
    if frame.empty:
        return pd.DataFrame(columns=["entry_time", "label", "target_index", "resolved_at", "resolution_bars", "outcome_sign"])
    frame["label_end_time"] = frame["resolved_at"]
    frame["label_end_index"] = frame["resolution_bars"].astype(int)
    return frame
