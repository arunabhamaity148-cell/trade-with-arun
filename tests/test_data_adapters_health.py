"""Adapter health and bug-fix regression tests."""
from __future__ import annotations

import pytest
import httpx

from twa.data.binance import BinanceAdapter
from twa.data.coinbase import CoinbaseAdapter
from twa.models.types import Timeframe


class _JsonResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _CoinbaseClient:
    async def get(self, *args, **kwargs):
        del args, kwargs
        newest_first = [
            [300, 9, 11, 10, 10.5, 1],
            [200, 8, 10, 9, 9.5, 1],
            [100, 7, 9, 8, 8.5, 1],
        ]
        return _JsonResponse(newest_first)


@pytest.mark.asyncio
async def test_coinbase_fetch_candles_keeps_latest_limit():
    adapter = CoinbaseAdapter(_CoinbaseClient())
    candles = await adapter.fetch_candles("BTCUSDT", Timeframe.H1, limit=2)
    assert [int(c.open_time.timestamp()) for c in candles] == [200, 300]


class _GeoBlockedClient:
    async def get(self, url, params=None, timeout=None):
        request = httpx.Request("GET", url, params=params)
        response = httpx.Response(403, request=request)
        raise httpx.HTTPStatusError("forbidden", request=request, response=response)


@pytest.mark.asyncio
async def test_binance_marks_geo_blocked_state():
    adapter = BinanceAdapter(_GeoBlockedClient())
    candles = await adapter.fetch_candles("BTCUSDT", Timeframe.H1, limit=2)
    assert candles == []
    health = adapter.health()
    assert health["known_state"] == "geo_blocked"
    assert health["recent_error_count"] >= 1
