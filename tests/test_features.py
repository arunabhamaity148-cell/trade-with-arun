"""Feature engineering tests."""
import math

from twa.features.engineering import (
    FEATURE_CATALOGUE, candles_to_frame, compute_all, list_features,
)
from twa.features.cross_exchange import (
    cross_exchange_dispersion, is_fresh, normalise_funding, oi_momentum,
    orderbook_imbalance,
)


def test_feature_catalogue_contract():
    names = list_features()
    assert isinstance(names, list)
    assert len(names) >= 6
    for k in names:
        spec = FEATURE_CATALOGUE[k]
        assert spec.purpose
        assert spec.formula


def test_compute_all_returns_all_features(synthetic_candles):
    feats = compute_all(synthetic_candles)
    for k in FEATURE_CATALOGUE:
        assert k in feats
        v = feats[k]
        assert isinstance(v, float)
        assert not (v != v)  # no NaNs


def test_compute_all_handles_empty():
    out = compute_all([])
    assert all(v == 0.0 for v in out.values())


def test_normalise_funding_finite(synthetic_funding):
    assert -1.0 <= normalise_funding(synthetic_funding) <= 1.0
    assert normalise_funding(None) == 0.0


def test_oi_momentum_finite():
    assert -1.0 <= oi_momentum(120.0, 100.0) <= 1.0
    assert oi_momentum(None, 100.0) == 0.0
    assert oi_momentum(100.0, None) == 0.0


def test_orderbook_imbalance_balanced_returns_zero():
    from twa.models.types import OrderBook, OrderBookLevel
    bids = [OrderBookLevel(price=100 - i, size=1.0) for i in range(5)]
    asks = [OrderBookLevel(price=101 + i, size=1.0) for i in range(5)]
    book = OrderBook(symbol="BTCUSDT", exchange="test", bids=bids, asks=asks)
    assert orderbook_imbalance(book) == 0.0


def test_orderbook_imbalance_bid_heavy(tiny_books):
    val = orderbook_imbalance(tiny_books)
    # tiny_books has 2x more size on the bid side, so imbalance should be positive.
    assert val > 0.0
    assert val <= 1.0


def test_cross_dispersion_zero_for_single_price():
    assert cross_exchange_dispersion([100]) == 0.0


def test_is_fresh_reasonable():
    from datetime import datetime, timedelta, timezone
    now = datetime.now(tz=timezone.utc)
    assert is_fresh(now, now)
    assert not is_fresh(now - timedelta(seconds=1200), max_age_s=600)
    assert not is_fresh(None)

