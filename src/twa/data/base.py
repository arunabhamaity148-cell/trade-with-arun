"""Abstract exchange adapter contract.

All adapters MUST be async-first, validate timestamps, normalise to ms-UTC,
and provide built-in retry/timeout via the HTTP client passed in.
"""
from __future__ import annotations

import abc
from typing import List, Optional

from twa.models.types import (
    Candle,
    FundingRate,
    OpenInterest,
    OrderBook,
    Ticker,
    Timeframe,
)

TF_TO_MS = {
    Timeframe.M1: 60_000,
    Timeframe.M5: 300_000,
    Timeframe.M15: 900_000,
    Timeframe.H1: 3_600_000,
    Timeframe.H4: 14_400_000,
    Timeframe.D1: 86_400_000,
}


class ExchangeAdapter(abc.ABC):
    """Base class for all exchange adapters.

    Adapters are stateless apart from optional session; they MUST:
      * Never raise on transient network errors → return empty + log
      * Normalise all timestamps to ms-UTC (already handled by Pydantic)
      * Validate prices/volumes (finite, positive)
      * Set `last_ok_ts` so the failover layer can detect stale feeds
    """

    name: str = "abstract"

    def __init__(self) -> None:
        self.last_ok_ts: Optional[float] = None
        self.last_error: Optional[str] = None

    @abc.abstractmethod
    async def fetch_candles(
        self, symbol: str, timeframe: Timeframe, limit: int = 500
    ) -> List[Candle]: ...

    @abc.abstractmethod
    async def fetch_ticker(self, symbol: str) -> Optional[Ticker]: ...

    @abc.abstractmethod
    async def fetch_orderbook(self, symbol: str, depth: int = 20) -> Optional[OrderBook]: ...

    async def fetch_funding(self, symbol: str) -> Optional[FundingRate]:
        """Optional — only implemented by exchanges that expose perps."""
        return None

    async def fetch_open_interest(self, symbol: str) -> Optional[OpenInterest]:
        """Optional — only implemented by exchanges that expose perps."""
        return None

    def health(self) -> dict:
        return {
            "exchange": self.name,
            "last_ok_ts": self.last_ok_ts,
            "last_error": self.last_error,
        }
