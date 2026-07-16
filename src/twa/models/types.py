"""Shared Pydantic models (typed data layer)."""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


def utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


class Side(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    NEUTRAL = "NEUTRAL"


class RegimeLabel(str, Enum):
    TREND_UP = "trend_up"
    TREND_DOWN = "trend_down"
    RANGE = "range"
    VOLATILE = "volatile"
    STRESSED = "stressed"


class Timeframe(str, Enum):
    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    H1 = "1h"
    H4 = "4h"
    D1 = "1d"


class Candle(BaseModel):
    """Single OHLCV candle, exchange-agnostic."""

    symbol: str
    exchange: str
    timeframe: Timeframe
    open_time: datetime
    close_time: Optional[datetime] = None
    open: float
    high: float
    low: float
    close: float
    volume: float
    quote_volume: Optional[float] = None
    trades: Optional[int] = None

    @field_validator("open_time", "close_time", mode="before")
    @classmethod
    def _ts_to_utc(cls, v):
        if v is None:
            return None
        if isinstance(v, (int, float)):
            return datetime.fromtimestamp(float(v) / 1000.0, tz=timezone.utc)
        if isinstance(v, datetime) and v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v

    @field_validator("open", "high", "low", "close", "volume")
    @classmethod
    def _finite(cls, v: float) -> float:
        f = float(v)
        if f != f or f in (float("inf"), float("-inf")):
            raise ValueError("non-finite price/volume")
        return f


class Ticker(BaseModel):
    """Best bid/ask + 24h stats."""

    symbol: str
    exchange: str
    bid: float
    ask: float
    last: float
    volume_24h: float
    change_pct_24h: float
    timestamp: datetime = Field(default_factory=utcnow)


class FundingRate(BaseModel):
    """Funding rate snapshot for a perpetual."""

    symbol: str
    exchange: str
    rate: float
    next_funding_time: Optional[datetime] = None
    timestamp: datetime = Field(default_factory=utcnow)


class OpenInterest(BaseModel):
    symbol: str
    exchange: str
    open_interest: float
    open_interest_value: Optional[float] = None
    timestamp: datetime = Field(default_factory=utcnow)


class OrderBookLevel(BaseModel):
    price: float
    size: float


class OrderBook(BaseModel):
    symbol: str
    exchange: str
    bids: List[OrderBookLevel]
    asks: List[OrderBookLevel]
    timestamp: datetime = Field(default_factory=utcnow)


class FeatureSnapshot(BaseModel):
    """Snapshot of all engineered features for a symbol/regime/timestamp."""

    symbol: str
    timeframe: Timeframe
    timestamp: datetime
    regime: RegimeLabel
    features: dict
    quality_flags: dict = Field(default_factory=dict)


class FactorContribution(BaseModel):
    """Single factor's contribution to a signal (explainability)."""

    name: str
    raw_value: float
    norm_value: float  # in [-1, +1]
    weight: float
    contribution: float  # weight * norm_value
    rationale: str


class NewsEvent(BaseModel):
    title: str
    source: str
    url: str
    published_at: datetime
    symbols: List[str] = Field(default_factory=list)
    severity: float = 0.0
    sentiment: float = 0.0
    category: str = "general"


class SignalIdea(BaseModel):
    """Final explainable trade idea."""

    id: str
    symbol: str
    exchange: str
    timeframe: Timeframe
    side: Side
    regime: RegimeLabel
    confidence: float  # 0..1
    expected_edge_bps: float
    entry_zone: List[float]  # [low, high]
    targets: List[float]  # TP levels
    invalidation: float
    rationale: List[str]
    factor_contributions: List[FactorContribution]
    news_dampen: float = 1.0
    news_events: List[NewsEvent] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)
    expires_at: Optional[datetime] = None
