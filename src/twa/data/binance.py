"""Binance public-market adapter (FREE, no auth required).

Sources:
  * Spot:     https://api.binance.com
  * Futures:  https://fapi.binance.com (USDⓈ-M perpetuals)
Both expose klines, 24h ticker, depth, funding, open-interest.

References:
  * https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/ws-streams/public
"""
from __future__ import annotations

from typing import List, Optional

import httpx

from twa.data.base import ExchangeAdapter
from twa.logging import get_logger
from twa.models.types import (
    Candle,
    FundingRate,
    OpenInterest,
    OrderBook,
    OrderBookLevel,
    Ticker,
    Timeframe,
)

log = get_logger("data.binance")

SPOT = "https://api.binance.com"
FUT  = "https://fapi.binance.com"


def _is_perp(symbol: str) -> bool:
    return symbol.endswith("USDT") and not symbol.endswith("USD")


def _tf_to_str(tf: Timeframe) -> str:
    return {"1m":"1m","5m":"5m","15m":"15m","1h":"1h","4h":"4h","1d":"1d"}[tf.value]


class BinanceAdapter(ExchangeAdapter):
    name = "binance"

    def __init__(self, client: httpx.AsyncClient):
        super().__init__()
        self.client = client

    async def fetch_candles(self, symbol: str, timeframe: Timeframe, limit: int = 500) -> List[Candle]:
        base = FUT if _is_perp(symbol) else SPOT
        params = {"symbol": symbol, "interval": _tf_to_str(timeframe), "limit": min(1000, limit)}
        try:
            r = await self.client.get(f"{base}/api/v3/klines", params=params, timeout=15.0)
            r.raise_for_status()
        except Exception as e:
            self.last_error = f"klines:{e!s}"
            log.warning("binance.klines.error", symbol=symbol, error=str(e))
            return []
        raw = r.json()
        out: List[Candle] = []
        for k in raw:
            try:
                c = Candle(
                    symbol=symbol,
                    exchange=self.name,
                    timeframe=timeframe,
                    open_time=int(k[0]),
                    close_time=int(k[6]),
                    open=float(k[1]),
                    high=float(k[2]),
                    low=float(k[3]),
                    close=float(k[4]),
                    volume=float(k[5]),
                    quote_volume=float(k[7]) if len(k) > 7 else None,
                    trades=int(k[8]) if len(k) > 8 else None,
                )
                out.append(c)
            except Exception as e:
                log.debug("binance.candle.parse.skip", err=str(e))
                continue
        self.last_ok_ts = out[-1].open_time.timestamp() if out else None
        self.last_error = None
        return out

    async def fetch_ticker(self, symbol: str) -> Optional[Ticker]:
        base = FUT if _is_perp(symbol) else SPOT
        path = "/fapi/v1/ticker/24hr" if base == FUT else "/api/v3/ticker/24hr"
        try:
            r = await self.client.get(f"{base}{path}", params={"symbol": symbol}, timeout=10.0)
            r.raise_for_status()
            d = r.json()
        except Exception as e:
            self.last_error = f"ticker:{e!s}"
            return None
        last = float(d.get("lastPrice", 0) or 0)
        bid = float(d.get("bidPrice", 0) or last)
        ask = float(d.get("askPrice", 0) or last)
        vol = float(d.get("volume", 0) or 0)
        chg = float(d.get("priceChangePercent", 0) or 0)
        if last <= 0:
            return None
        return Ticker(symbol=symbol, exchange=self.name, bid=bid, ask=ask, last=last,
                      volume_24h=vol, change_pct_24h=chg)

    async def fetch_orderbook(self, symbol: str, depth: int = 20) -> Optional[OrderBook]:
        base = FUT if _is_perp(symbol) else SPOT
        path = "/fapi/v1/depth" if base == FUT else "/api/v3/depth"
        try:
            r = await self.client.get(f"{base}{path}", params={"symbol": symbol, "limit": depth}, timeout=10.0)
            r.raise_for_status()
            d = r.json()
        except Exception as e:
            self.last_error = f"depth:{e!s}"
            return None
        bids = [OrderBookLevel(price=float(b[0]), size=float(b[1])) for b in d.get("bids", [])]
        asks = [OrderBookLevel(price=float(a[0]), size=float(a[1])) for a in d.get("asks", [])]
        return OrderBook(symbol=symbol, exchange=self.name, bids=bids, asks=asks)

    async def fetch_funding(self, symbol: str) -> Optional[FundingRate]:
        if not _is_perp(symbol):
            return None
        try:
            r = await self.client.get(f"{FUT}/fapi/v1/fundingRate", params={"symbol": symbol, "limit": 1}, timeout=10.0)
            r.raise_for_status()
            arr = r.json()
            if not arr:
                return None
            d = arr[-1]
            return FundingRate(
                symbol=symbol, exchange=self.name,
                rate=float(d.get("fundingRate", 0.0)),
                next_funding_time=int(d.get("fundingTime", 0)) or None,
            )
        except Exception as e:
            self.last_error = f"funding:{e!s}"
            return None

    async def fetch_open_interest(self, symbol: str) -> Optional[OpenInterest]:
        if not _is_perp(symbol):
            return None
        try:
            r = await self.client.get(f"{FUT}/fapi/v1/openInterest", params={"symbol": symbol}, timeout=10.0)
            r.raise_for_status()
            d = r.json()
            oi = float(d.get("openInterest", 0))
            return OpenInterest(symbol=symbol, exchange=self.name, open_interest=oi,
                                open_interest_value=None)
        except Exception as e:
            self.last_error = f"oi:{e!s}"
            return None
