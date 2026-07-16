"""Cross-exchange / derivatives features (funding, basis, OI, OBI).

These features are computed by the orchestrator when the relevant data is
available.  All of them are fail-safe — they return 0.0 if the data is
missing. They are also used to populate `FeatureSnapshot.quality_flags`.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from twa.models.types import (
    FundingRate, OpenInterest, OrderBook,
)


def normalise_funding(funding: Optional[FundingRate]) -> float:
    """Funding rate scaled to [-1, +1] (funding is per 8h, ±0.03% is large).

    formula = clamp(rate / 0.0005, -1, +1)
    """
    if funding is None:
        return 0.0
    return max(-1.0, min(1.0, funding.rate / 0.0005))


def oi_momentum(current: Optional[float], prior: Optional[float]) -> float:
    """Return OI change as -1..+1 around ±5% to capture new-money inflows/outflows.

    if either is None → 0.0
    """
    if current is None or prior is None or prior == 0:
        return 0.0
    pct = (current - prior) / prior
    return max(-1.0, min(1.0, pct / 0.05))


def orderbook_imbalance(book: Optional[OrderBook], depth: int = 10) -> float:
    """Best-N imbalance in [-1, +1]: +1 = strong bid pressure; -1 = ask pressure.

    formula = (Σ bid_size - Σ ask_size) / (Σ bid_size + Σ ask_size)
    """
    if book is None:
        return 0.0
    bids = sum(lvl.size for lvl in book.bids[:depth])
    asks = sum(lvl.size for lvl in book.asks[:depth])
    denom = bids + asks
    if denom == 0:
        return 0.0
    return (bids - asks) / denom


def cross_exchange_dispersion(prices) -> float:
    """Coefficient of variation across exchange last prices.

    Higher dispersion ⇒ noisier signal. Aggregator logs a warning above 10%.
    """
    if not prices or len(prices) < 2:
        return 0.0
    mean = sum(prices) / len(prices)
    if mean == 0:
        return 0.0
    var = sum((p - mean) ** 2 for p in prices) / len(prices)
    return float((var ** 0.5) / mean)


def is_fresh(ts: Optional[datetime], now: Optional[datetime] = None, max_age_s: int = 600) -> bool:
    """True if a timestamp is within `max_age_s` of now."""
    if ts is None:
        return False
    now = now or datetime.now(tz=timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return abs((now - ts).total_seconds()) <= max_age_s
