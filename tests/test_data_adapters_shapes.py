"""Data adapter structural tests (no live HTTP calls in CI)."""
import asyncio

from twa.models.types import Timeframe


def test_bybit_category_detector():
    from twa.data.bybit import _category
    assert _category("BTCUSDT") == "linear"
    assert _category("BTCUSD") == "spot"


def test_binance_perp_detector():
    from twa.data.binance import _is_perp
    assert _is_perp("BTCUSDT")
    assert not _is_perp("BTCUSDC")
    assert not _is_perp("BTCUSD")


def test_binance_tf_to_str():
    from twa.data.binance import _tf_to_str
    assert _tf_to_str(Timeframe.H1) == "1h"


def test_bybit_tf_mapping():
    from twa.data.bybit import _tf_to_bybit
    assert _tf_to_bybit(Timeframe.D1) == "D"


def test_aggregator_constructs_with_only_binance():
    from twa.config import Settings
    from twa.data.cache import MarketDataAggregator
    s = Settings(exchanges=["binance"])
    agg = MarketDataAggregator(s)
    try:
        assert "binance" in agg.adapters
        assert "bybit" not in agg.adapters
    finally:
        asyncio.run(agg.close())
