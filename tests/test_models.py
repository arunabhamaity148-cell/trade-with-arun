"""Pydantic model validation tests."""
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from twa.models.types import (
    Candle, FundingRate, OpenInterest, OrderBook, OrderBookLevel, Side,
    RegimeLabel, SignalIdea, Timeframe,
)


def test_candle_parses_millisecond_timestamp():
    c = Candle(
        symbol="BTCUSDT", exchange="binance", timeframe=Timeframe.H1,
        open_time=1_700_000_000_000, open=1, high=2, low=0.5, close=1.5, volume=10,
    )
    assert isinstance(c.open_time, datetime)
    assert c.open_time.tzinfo is timezone.utc


def test_candle_rejects_nan():
    with pytest.raises(ValidationError):
        Candle(
            symbol="BTCUSDT", exchange="binance", timeframe=Timeframe.H1,
            open_time=0, open=float("nan"), high=2, low=0.5, close=1.5, volume=10,
        )


def test_signal_idea_side_default_neutral():
    s = SignalIdea(
        id="x", symbol="BTCUSDT", exchange="binance", timeframe=Timeframe.H1,
        side=Side.NEUTRAL, regime=RegimeLabel.RANGE, confidence=0.0,
        expected_edge_bps=0.0, entry_zone=[0.0, 0.0], targets=[0.0],
        invalidation=0.0, rationale=[], factor_contributions=[],
    )
    assert s.side == Side.NEUTRAL


def test_candle_minimum_ok():
    c = Candle(
        symbol="ETHUSDT", exchange="bybit", timeframe=Timeframe.M15,
        open_time=datetime.now(tz=timezone.utc),
        open=100, high=101, low=99, close=100.5, volume=5,
    )
    assert c.close == 100.5
