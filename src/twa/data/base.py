"""Abstract exchange adapter contract.

All adapters MUST be async-first, validate timestamps, normalise to ms-UTC,
and provide built-in retry/timeout via the HTTP client passed in.
"""
from __future__ import annotations

import abc
import time
from collections import deque
from typing import Deque, List, Optional, Tuple

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

_HEALTH_WINDOW_S = 900.0


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
        self.known_state: Optional[str] = None
        self.status_flags: set[str] = set()
        self._events: Deque[Tuple[float, bool]] = deque(maxlen=512)

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

    def record_success(self) -> None:
        now = time.time()
        self.last_ok_ts = now
        self._events.append((now, True))
        self._prune_events(now)

    def record_error(self, error: str, *, known_state: Optional[str] = None) -> None:
        now = time.time()
        self.last_error = error
        self._events.append((now, False))
        if known_state:
            self.known_state = known_state
            self.status_flags.add(known_state)
        self._prune_events(now)

    def clear_error(self, *, clear_known_state: bool = False, flags: Optional[List[str]] = None) -> None:
        self.last_error = None
        if flags:
            for flag in flags:
                self.status_flags.discard(flag)
        if clear_known_state:
            self.known_state = None

    def health(self) -> dict:
        now = time.time()
        self._prune_events(now)
        errors = sum(1 for _, ok in self._events if not ok)
        successes = sum(1 for _, ok in self._events if ok)
        total = errors + successes
        return {
            "exchange": self.name,
            "last_ok_ts": self.last_ok_ts,
            "last_error": self.last_error,
            "known_state": self.known_state,
            "status_flags": sorted(self.status_flags),
            "recent_error_count": errors,
            "recent_success_count": successes,
            "recent_error_rate": float(errors / total) if total else 0.0,
            "recent_window_s": _HEALTH_WINDOW_S,
        }

    def _prune_events(self, now: Optional[float] = None) -> None:
        now = now or time.time()
        while self._events and (now - self._events[0][0]) > _HEALTH_WINDOW_S:
            self._events.popleft()
