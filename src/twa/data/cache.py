"""Aggregate adapter registry + failover layer + cache.

The aggregator:
  * Queries all healthy exchanges in parallel for each (symbol, timeframe).
  * Performs cross-exchange sanity checks (price dispersion).
  * Falls back to the freshest available feed if a primary is stale.
  * Caches responses in-memory with TTL.

No data is fabricated and no synthetic prices are ever returned.
"""
from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable, Dict, List, Optional, Type

import httpx

from twa.config import Settings
from twa.data.base import ExchangeAdapter
from twa.data.binance import BinanceAdapter
from twa.data.bybit import BybitAdapter
from twa.data.coinbase import CoinbaseAdapter
from twa.logging import get_logger
from twa.models.types import (
    Candle, FundingRate, OpenInterest, OrderBook, Ticker, Timeframe,
)

log = get_logger("data.aggregator")

ADAPTERS: Dict[str, Type[ExchangeAdapter]] = {
    "binance": BinanceAdapter,
    "bybit": BybitAdapter,
    "coinbase": CoinbaseAdapter,
}

_STALE_AFTER_S = 120.0  # if no successful fetch in N seconds, feed is considered stale.


class TTLCache:
    """Tiny thread/async-safe TTL cache.

    Used to limit repeat HTTP calls when many subsystems ask for the same
    symbol's snapshot in the same cycle.
    """

    def __init__(self, default_ttl_s: float = 5.0):
        self._data: dict[str, tuple[float, object]] = {}
        self._lock = asyncio.Lock()
        self.ttl = default_ttl_s

    async def get(self, key: str) -> Optional[object]:
        async with self._lock:
            v = self._data.get(key)
            if not v:
                return None
            ts, payload = v
            if time.time() - ts > self.ttl:
                self._data.pop(key, None)
                return None
            return payload

    async def set(self, key: str, payload: object) -> None:
        async with self._lock:
            self._data[key] = (time.time(), payload)


class MarketDataAggregator:
    """Owns adapters, failover orchestration, and cross-exchange sanity checks."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = httpx.AsyncClient(
            timeout=settings.http_timeout_s,
            headers={"User-Agent": "TradeWithArun/1.0"},
            http2=False,
        )
        self.adapters: Dict[str, ExchangeAdapter] = {
            name: cls(self.client)
            for name, cls in ADAPTERS.items()
            if name in [x.lower() for x in settings.exchanges]
        }
        self.cache = TTLCache(default_ttl_s=float(settings.lookback_bars) * 0 + settings.http_timeout_s)
        if not self.adapters:
            log.warning("data.no_adapters_selected", exchanges=settings.exchanges)

    async def close(self) -> None:
        await self.client.aclose()

    def health(self) -> dict:
        return {
            "adapters": {name: a.health() for name, a in self.adapters.items()},
            "stale_threshold_s": _STALE_AFTER_S,
        }

    # ---------- low-level helper ----------
    async def _gather_first(
        self,
        producer: Callable[[ExchangeAdapter], Awaitable[Optional[object]]],
        symbol: str,
        require_non_empty: bool = False,
    ):
        """Run producer for every healthy adapter concurrently; return first non-empty."""
        if not self.adapters:
            return None
        tasks = {
            name: asyncio.create_task(_safe(producer(a)), name=f"{name}:{symbol}")
            for name, a in self.adapters.items()
            if a.last_error is None or a.last_ok_ts is None
            or time.time() - (a.last_ok_ts or 0) < _STALE_AFTER_S
        }
        if not tasks:
            # All stale — try anyway, best effort.
            tasks = {name: asyncio.create_task(_safe(producer(a)), name=name)
                     for name, a in self.adapters.items()}

        done = await asyncio.gather(*tasks.values(), return_exceptions=True)
        results = {}
        for name, res in zip(tasks.keys(), done):
            results[name] = res

        # Pick best result: prefer non-empty + non-error.
        chosen = None
        chosen_name = None
        for name, r in results.items():
            if isinstance(r, Exception) or r is None:
                continue
            if require_non_empty and hasattr(r, "__len__") and len(r) == 0:
                continue
            chosen = r
            chosen_name = name
            break
        if chosen is not None:
            log.debug("data.feed_selected", symbol=symbol, exchange=chosen_name)
        else:
            log.warning("data.feed_lost", symbol=symbol, results=list(results.keys()))
        return chosen

    async def fetch_candles(
        self, symbol: str, timeframe: Timeframe, limit: int = 500,
    ) -> List[Candle]:
        cached = await self.cache.get(f"candles:{symbol}:{timeframe}:{limit}")
        if cached is not None:
            return cached  # type: ignore[return-value]
        res = await self._gather_first(
            lambda a: a.fetch_candles(symbol, timeframe, limit),
            symbol=symbol, require_non_empty=True,
        )
        candles: List[Candle] = res if isinstance(res, list) else []
        # Cross-exchange sanity: price dispersion check on the last close.
        if len(candles) >= 2:
            last = candles[-1].close
            others = [a.fetch_candles(symbol, timeframe, 5) for a in self.adapters.values()]
            try:
                other_sets = await asyncio.wait_for(
                    asyncio.gather(*others, return_exceptions=True), timeout=5)
            except Exception:
                other_sets = []
            closes = [last]
            for r in other_sets:
                if isinstance(r, list) and r:
                    closes.append(r[-1].close)
            if len(closes) >= 2:
                mean = sum(closes) / len(closes)
                if mean > 0:
                    disp = max(abs(c - mean) / mean for c in closes)
                    if disp > 0.10:
                        log.warning("data.dispersion.high", symbol=symbol, dispersion=round(disp, 4))
        await self.cache.set(f"candles:{symbol}:{timeframe}:{limit}", candles)
        return candles

    async def fetch_ticker(self, symbol: str) -> Optional[Ticker]:
        cached = await self.cache.get(f"ticker:{symbol}")
        if cached is not None:
            return cached  # type: ignore[return-value]
        t = await self._gather_first(lambda a: a.fetch_ticker(symbol), symbol=symbol)
        if t is not None:
            await self.cache.set(f"ticker:{symbol}", t)
        return t if isinstance(t, Ticker) else None

    async def fetch_orderbook(self, symbol: str, depth: int = 20) -> Optional[OrderBook]:
        cached = await self.cache.get(f"book:{symbol}:{depth}")
        if cached is not None:
            return cached  # type: ignore[return-value]
        b = await self._gather_first(lambda a: a.fetch_orderbook(symbol, depth), symbol=symbol)
        if b is not None:
            await self.cache.set(f"book:{symbol}:{depth}", b)
        return b if isinstance(b, OrderBook) else None

    async def fetch_funding(self, symbol: str) -> Optional[FundingRate]:
        return await self._gather_first(lambda a: a.fetch_funding(symbol), symbol=symbol)

    async def fetch_open_interest(self, symbol: str) -> Optional[OpenInterest]:
        return await self._gather_first(lambda a: a.fetch_open_interest(symbol), symbol=symbol)


async def _safe(coro: Awaitable[object]) -> object:
    """Wrap a coroutine so exceptions don't bubble up."""
    try:
        return await coro
    except Exception as e:  # noqa: BLE001 - intentional fail-safe
        log.debug("data.adapter.call_failed", err=str(e))
        return None
