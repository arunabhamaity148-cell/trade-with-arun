"""Test setup: generate a deterministic synthetic candle series for tests."""
from __future__ import annotations

import math
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

# Allow `from tests.conftest import make_candles` in both
# `pytest` collection and direct import paths.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from twa.models.types import (
    Candle, FundingRate, OpenInterest, OrderBook, OrderBookLevel, Timeframe,
)


def _seeded(seed: int = 42) -> random.Random:
    return random.Random(seed)


def make_candles(n: int = 400, start: float = 30_000.0, drift: float = 0.0,
                 vol: float = 0.01, seed: int = 42,
                 timeframe: Timeframe = Timeframe.H1,
                 symbol: str = "BTCUSDT", exchange: str = "test") -> list[Candle]:
    """Deterministic synthetic candle stream used by every unit test."""
    rng = _seeded(seed)
    candles: list[Candle] = []
    t = datetime(2024, 1, 1, tzinfo=timezone.utc)
    price = start
    minutes = {"1m":1,"5m":5,"15m":15,"1h":60,"4h":240,"1d":1440}[timeframe.value]
    for i in range(n):
        step = math.exp(drift / n + vol * rng.gauss(0, 1))
        open_p = price
        close_p = price * step
        high_p = max(open_p, close_p) * (1 + abs(rng.gauss(0, 0.001)))
        low_p = min(open_p, close_p) * (1 - abs(rng.gauss(0, 0.001)))
        vol_qty = max(1.0, rng.random() * 1000.0)
        candles.append(Candle(
            symbol=symbol, exchange=exchange, timeframe=timeframe,
            open_time=t, close_time=t, open=open_p, high=high_p, low=low_p,
            close=close_p, volume=vol_qty,
        ))
        price = close_p
        t = t + timedelta(minutes=minutes)
    return candles


@pytest.fixture
def synthetic_candles():
    return make_candles()


@pytest.fixture
def synthetic_long_run():
    return make_candles(n=600, start=20_000.0, drift=0.6, vol=0.012)


@pytest.fixture
def tiny_books():
    bids = [OrderBookLevel(price=100.0 - i * 0.1, size=1.0 + i) for i in range(10)]
    asks = [OrderBookLevel(price=100.1 + i * 0.1, size=1.0) for i in range(10)]
    return OrderBook(symbol="BTCUSDT", exchange="test", bids=bids, asks=asks)


@pytest.fixture
def synthetic_funding():
    return FundingRate(symbol="BTCUSDT", exchange="test", rate=0.0002)


@pytest.fixture
def synthetic_oi():
    return OpenInterest(symbol="BTCUSDT", exchange="test", open_interest=50_000.0)
