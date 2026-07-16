"""Bybit v5 public-market adapter (FREE, no auth).

Sources:
  * https://api.bybit.com
  * https://api.bybit.com/v5/market/*
Endpoints used: kline, tickers, orderbook, funding-history, open-interest.

Reference: https://bybit-exchange.github.io/docs/v5/market/kline
"""
from __future__ import annotations

from typing import List, Optional

import httpx

from twa.data.base import ExchangeAdapter
from twa.logging import get_logger
from twa.models.types import (
    Candle, FundingRate, OpenInterest, OrderBook, OrderBookLevel, Ticker, Timeframe,
)

log = get_logger("data.bybit")

BASE = "https://api.bybit.com"
CATEGORY_PERP = "linear"


def _tf_to_bybit(tf: Timeframe) -> str:
    return {"1m": "1", "5m": "5", "15m": "15", "1h": "60", "4h": "240", "1d": "D"}[tf.value]


def _category(symbol: str) -> str:
    if symbol.endswith("USDT"):
        return "linear"
    return "spot"


class BybitAdapter(ExchangeAdapter):
    name = "bybit"

    def __init__(self, client: httpx.AsyncClient):
        super().__init__()
        self.client = client

    async def fetch_candles(self, symbol: str, timeframe: Timeframe, limit: int = 500) -> List[Candle]:
        cat = _category(symbol)
        params = {"category": cat, "symbol": symbol, "interval": _tf_to_bybit(timeframe),
                  "limit": min(1000, limit)}
        try:
            r = await self.client.get(f"{BASE}/v5/market/kline", params=params, timeout=15.0)
            r.raise_for_status()
            d = r.json()
        except Exception as e:
            self.record_error(f"klines:{e!s}")
            log.warning("bybit.klines.error", symbol=symbol, error=str(e))
            return []
        lst = (d.get("result") or {}).get("list") or []
        out: List[Candle] = []
        for k in lst:  # Bybit returns [ts, o, h, l, c, vol, turnover]
            try:
                c = Candle(
                    symbol=symbol, exchange=self.name, timeframe=timeframe,
                    open_time=int(k[0]), close_time=None,
                    open=float(k[1]), high=float(k[2]), low=float(k[3]),
                    close=float(k[4]), volume=float(k[5]),
                    quote_volume=float(k[6]) if len(k) > 6 else None,
                )
                out.append(c)
            except Exception as e:
                log.debug("bybit.candle.parse.skip", err=str(e))
                continue
        out.sort(key=lambda c: c.open_time.timestamp())
        if out:
            self.record_success()
            self.clear_error()
        return out

    async def fetch_ticker(self, symbol: str) -> Optional[Ticker]:
        cat = _category(symbol)
        try:
            r = await self.client.get(
                f"{BASE}/v5/market/tickers",
                params={"category": cat, "symbol": symbol},
                timeout=10.0,
            )
            r.raise_for_status()
            d = r.json()
            lst = (d.get("result") or {}).get("list") or []
            if not lst:
                return None
            t = lst[0]
            last = float(t.get("lastPrice", 0) or 0)
            bid = float(t.get("bid1Price", 0) or last)
            ask = float(t.get("ask1Price", 0) or last)
            vol = float(t.get("volume24h", 0) or 0)
            chg = float(t.get("price24hPcnt", 0) or 0) * 100.0
            if last <= 0:
                return None
            self.record_success()
            self.clear_error()
            return Ticker(symbol=symbol, exchange=self.name, bid=bid, ask=ask,
                          last=last, volume_24h=vol, change_pct_24h=chg)
        except Exception as e:
            self.record_error(f"ticker:{e!s}")
            return None

    async def fetch_orderbook(self, symbol: str, depth: int = 20) -> Optional[OrderBook]:
        cat = _category(symbol)
        try:
            r = await self.client.get(
                f"{BASE}/v5/market/orderbook",
                params={"category": cat, "symbol": symbol, "limit": depth},
                timeout=10.0,
            )
            r.raise_for_status()
            d = r.json()
            res = d.get("result") or {}
            bids = [OrderBookLevel(price=float(b[0]), size=float(b[1])) for b in res.get("b", [])]
            asks = [OrderBookLevel(price=float(a[0]), size=float(a[1])) for a in res.get("a", [])]
            self.record_success()
            self.clear_error()
            return OrderBook(symbol=symbol, exchange=self.name, bids=bids, asks=asks)
        except Exception as e:
            self.record_error(f"depth:{e!s}")
            return None

    async def fetch_funding(self, symbol: str) -> Optional[FundingRate]:
        if _category(symbol) != "linear":
            return None
        try:
            r = await self.client.get(
                f"{BASE}/v5/market/funding/history",
                params={"category": "linear", "symbol": symbol, "limit": 1},
                timeout=10.0,
            )
            r.raise_for_status()
            d = r.json()
            lst = (d.get("result") or {}).get("list") or []
            if not lst:
                return None
            f = lst[0]
            self.record_success()
            self.clear_error()
            return FundingRate(
                symbol=symbol, exchange=self.name,
                rate=float(f.get("fundingRate", 0.0)),
            )
        except Exception as e:
            self.record_error(f"funding:{e!s}")
            return None

    async def fetch_open_interest(self, symbol: str) -> Optional[OpenInterest]:
        if _category(symbol) != "linear":
            return None
        try:
            r = await self.client.get(
                f"{BASE}/v5/market/open-interest",
                params={"category": "linear", "symbol": symbol,
                        "intervalTime": "5min", "limit": 1},
                timeout=10.0,
            )
            r.raise_for_status()
            d = r.json()
            lst = (d.get("result") or {}).get("list") or []
            if not lst:
                return None
            o = lst[0]
            self.record_success()
            self.clear_error()
            return OpenInterest(
                symbol=symbol, exchange=self.name,
                open_interest=float(o.get("openInterest", 0)),
                open_interest_value=float(o.get("value", 0)) or None,
            )
        except Exception as e:
            self.record_error(f"oi:{e!s}")
            return None
