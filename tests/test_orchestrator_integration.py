"""End-to-end orchestrator demo using synthetic data (offline)."""
import asyncio

import pytest

from twa.config import Settings
from twa.models.types import (
    FundingRate, OpenInterest, OrderBook, OrderBookLevel, Timeframe, RegimeLabel,
)
from twa.orchestration.engine import Orchestrator
from tests.conftest import make_candles


class _FakeAggregator:
    """Drop-in replacement that never touches the network."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.adapters = {}

    async def fetch_candles(self, symbol, timeframe, limit=500):
        tf = timeframe if isinstance(timeframe, Timeframe) else Timeframe(timeframe)
        return make_candles(n=300, start=10_000.0, drift=8.0, vol=0.001,
                            timeframe=tf, symbol=symbol)

    async def fetch_funding(self, symbol):
        return FundingRate(symbol=symbol, exchange="test", rate=0.0001)

    async def fetch_open_interest(self, symbol):
        return OpenInterest(symbol=symbol, exchange="test", open_interest=42_000.0)

    async def fetch_orderbook(self, symbol, depth=20):
        bids = [OrderBookLevel(price=10_000 - i, size=1.0) for i in range(depth)]
        asks = [OrderBookLevel(price=10_001 + i, size=1.0) for i in range(depth)]
        return OrderBook(symbol=symbol, exchange="test", bids=bids, asks=asks)

    async def fetch_ticker(self, symbol):
        return None

    def health(self):
        return {"adapters": {}, "stale_threshold_s": 120}

    async def close(self):
        return None


@pytest.mark.asyncio
async def test_one_cycle_emits_signal():
    s = Settings(symbols=["BTCUSDT"])
    orch = Orchestrator(s)
    orch.data = _FakeAggregator(s)
    try:
        sig = await orch._one_symbol("BTCUSDT")
        assert sig is not None
        assert sig.symbol == "BTCUSDT"
        assert 0.05 <= sig.news_dampen <= 1.0
        assert isinstance(sig.regime, RegimeLabel)
    finally:
        await orch.stop()
