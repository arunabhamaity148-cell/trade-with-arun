"""Coinbase Exchange (formerly GDAX/Pro) public adapter (FREE, no auth).

Sources:
  * https://api.exchange.coinbase.com
Endpoints used: products/{id}/candles, products/{id}/ticker, products/{id}/book.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

import httpx

from twa.data.base import ExchangeAdapter
from twa.logging import get_logger
from twa.models.types import (
    Candle, OrderBook, OrderBookLevel, Ticker, Timeframe,
)

log = get_logger("data.coinbase")

BASE = "https://api.exchange.coinbase.com"


def _is_supported(symbol: str) -> bool:
    return symbol in {"BTCUSDT", "ETHUSDT"} or symbol in {"BTC-USD", "ETH-USD"}


def _product_id(symbol: str) -> str:
    return {"BTCUSDT": "BTC-USD", "ETHUSDT": "ETH-USD"}[symbol] if symbol.endswith("USDT") else symbol


def _tf_to_coinbase(tf: Timeframe) -> int:
    return {"1m":60,"5m":300,"15m":900,"1h":3600,"4h":14400,"1d":86400}[tf.value]


class CoinbaseAdapter(ExchangeAdapter):
    name = "coinbase"

    def __init__(self, client: httpx.AsyncClient):
        super().__init__()
        self.client = client

    async def fetch_candles(self, symbol: str, timeframe: Timeframe, limit: int = 500) -> List[Candle]:
        if not _is_supported(symbol):
            self.last_error = "unsupported_symbol"
            return []
        pid = _product_id(symbol)
        granularity = _tf_to_coinbase(timeframe)
        try:
            r = await self.client.get(f"{BASE}/products/{pid}/candles",
                                      params={"granularity": granularity}, timeout=15.0)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            self.last_error = f"candles:{e!s}"
            log.warning("coinbase.candles.error", symbol=symbol, error=str(e))
            return []
        out: List[Candle] = []
        # Coinbase returns newest-first: [time, low, high, open, close, volume]
        for row in sorted(data, key=lambda x: x[0])[:limit]:
            try:
                ts = int(row[0])
                c = Candle(
                    symbol=symbol, exchange=self.name, timeframe=timeframe,
                    open_time=datetime.fromtimestamp(ts, tz=timezone.utc),
                    close_time=None,
                    open=float(row[3]), high=float(row[2]),
                    low=float(row[1]), close=float(row[4]),
                    volume=float(row[5]),
                )
                out.append(c)
            except Exception as e:
                log.debug("coinbase.candle.parse.skip", err=str(e))
                continue
        self.last_ok_ts = out[-1].open_time.timestamp() if out else None
        self.last_error = None
        return out

    async def fetch_ticker(self, symbol: str) -> Optional[Ticker]:
        if not _is_supported(symbol):
            return None
        pid = _product_id(symbol)
        try:
            r = await self.client.get(f"{BASE}/products/{pid}/ticker", timeout=10.0)
            r.raise_for_status()
            d = r.json()
            price = float(d.get("price", 0) or 0)
            return Ticker(symbol=symbol, exchange=self.name, bid=price, ask=price, last=price,
                          volume_24h=float(d.get("volume", 0) or 0), change_pct_24h=0.0)
        except Exception as e:
            self.last_error = f"ticker:{e!s}"
            return None

    async def fetch_orderbook(self, symbol: str, depth: int = 20) -> Optional[OrderBook]:
        if not _is_supported(symbol):
            return None
        pid = _product_id(symbol)
        try:
            r = await self.client.get(f"{BASE}/products/{pid}/book",
                                      params={"level": 2}, timeout=10.0)
            r.raise_for_status()
            d = r.json()
            bids = [OrderBookLevel(price=float(b[0]), size=float(b[1])) for b in d.get("bids", [])][:depth]
            asks = [OrderBookLevel(price=float(a[0]), size=float(a[1])) for a in d.get("asks", [])][:depth]
            return OrderBook(symbol=symbol, exchange=self.name, bids=bids, asks=asks)
        except Exception as e:
            self.last_error = f"depth:{e!s}"
            return None
