"""Research composition root for offline datasets and feature frames."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd

from twa.config import Settings
from twa.data.cache import MarketDataAggregator
from twa.features.engineering import candles_to_frame, compute_all
from twa.logging import get_logger
from twa.models.types import Candle, Timeframe, coerce_timeframe
from twa.regime.classifier import classify
from twa.research.utils import ensure_research_dir, estimate_bar_count, forward_returns

log = get_logger("research.lab")


@dataclass
class ResearchSession:
    settings: Settings
    symbol: str
    timeframe: Timeframe
    candles: List[Candle]
    frame: pd.DataFrame
    feature_frame: pd.DataFrame
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    snapshots: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_candles(
        cls,
        settings: Settings,
        symbol: str,
        timeframe: Timeframe | str,
        candles: List[Candle],
        *,
        started_at: Optional[datetime] = None,
        ended_at: Optional[datetime] = None,
        snapshots: Optional[Dict[str, Any]] = None,
    ) -> "ResearchSession":
        tf = coerce_timeframe(timeframe)
        ordered = sorted(candles, key=lambda c: c.open_time)
        frame = candles_to_frame(ordered).copy()
        frame.insert(0, "timestamp", [c.open_time for c in ordered])
        frame.insert(1, "symbol", symbol)
        feature_frame = _build_feature_frame(symbol, ordered)
        return cls(
            settings=settings,
            symbol=symbol,
            timeframe=tf,
            candles=ordered,
            frame=frame,
            feature_frame=feature_frame,
            started_at=started_at or (ordered[0].open_time if ordered else None),
            ended_at=ended_at or (ordered[-1].open_time if ordered else None),
            snapshots=snapshots or {},
        )

    @property
    def research_dir(self):
        return ensure_research_dir(self.settings)

    def target_frame(self, horizon: int = 4) -> pd.DataFrame:
        df = self.feature_frame.copy()
        df["forward_return"] = forward_returns(df["close"], horizon)
        df["forward_return_bps"] = df["forward_return"] * 10_000.0
        return df.dropna(subset=["forward_return"]).reset_index(drop=True)


class ResearchLab:
    """Load historical inputs and expose ResearchSession objects."""

    def __init__(self, settings: Settings, data: Optional[MarketDataAggregator] = None):
        self.settings = settings
        self.data = data or MarketDataAggregator(settings)
        self._owns_data = data is None

    async def close(self) -> None:
        if self._owns_data:
            await self.data.close()

    async def load_session(
        self,
        symbol: str,
        timeframe: Timeframe | str,
        *,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        limit: Optional[int] = None,
        candles: Optional[List[Candle]] = None,
    ) -> ResearchSession:
        tf = coerce_timeframe(timeframe)
        selected = candles
        if selected is None:
            fetch_limit = limit or self.settings.lookback_bars
            if start and end and limit is None:
                fetch_limit = max(fetch_limit, estimate_bar_count(start, end, tf))
            selected = await self.data.fetch_candles(symbol, tf, limit=fetch_limit)
        if start is not None:
            selected = [c for c in selected if c.open_time >= start]
        if end is not None:
            selected = [c for c in selected if c.open_time <= end]
        snapshots = {"funding": None, "open_interest": None, "orderbook": None}
        if candles is None:
            funding, oi, book = await self._load_snapshots(symbol)
            snapshots = {"funding": funding, "open_interest": oi, "orderbook": book}
        session = ResearchSession.from_candles(
            self.settings,
            symbol,
            tf,
            selected,
            started_at=start,
            ended_at=end,
            snapshots=snapshots,
        )
        log.info("research.session.loaded", symbol=symbol, timeframe=tf.value, candles=len(session.candles))
        return session

    async def _load_snapshots(self, symbol: str):
        funding = await self.data.fetch_funding(symbol)
        oi = await self.data.fetch_open_interest(symbol)
        book = await self.data.fetch_orderbook(symbol, depth=20)
        return funding, oi, book


def _build_feature_frame(symbol: str, candles: List[Candle], min_history: int = 64) -> pd.DataFrame:
    rows: List[dict] = []
    if not candles:
        return pd.DataFrame(columns=["timestamp", "symbol", "close", "regime"])
    for idx in range(min_history - 1, len(candles)):
        window = candles[:idx + 1]
        feats = compute_all(window)
        row = {
            "timestamp": candles[idx].open_time,
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
