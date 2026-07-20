"""Public research-only market data helpers.

These helpers intentionally avoid authenticated/private trading endpoints and are
used only by offline research scripts. They provide a deterministic workaround
when some exchange APIs are geo-restricted from the runtime environment.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Optional

import httpx
import pandas as pd

from twa.logging import get_logger

log = get_logger("research.public_market_data")

_OKX_CANDLES = "https://www.okx.com/api/v5/market/history-candles"
_OKX_FUNDING = "https://www.okx.com/api/v5/public/funding-rate-history"
_OKX_OPEN_INTEREST = "https://www.okx.com/api/v5/rubik/stat/contracts/open-interest-history"
_DEFAULT_HEADERS = {"User-Agent": "Mozilla/5.0"}


def _ts(ms: str | int | float) -> datetime:
    return datetime.fromtimestamp(float(ms) / 1000.0, tz=timezone.utc)


async def fetch_okx_hourly_candles(
    client: httpx.AsyncClient,
    inst_id: str,
    *,
    bars: int,
) -> pd.DataFrame:
    rows = []
    after: Optional[str] = None
    while len(rows) < bars:
        limit = min(100, bars - len(rows))
        params = {"instId": inst_id, "bar": "1H", "limit": str(limit)}
        if after is not None:
            params["after"] = after
        resp = await client.get(_OKX_CANDLES, params=params, headers=_DEFAULT_HEADERS)
        resp.raise_for_status()
        data = (resp.json() or {}).get("data") or []
        if not data:
            break
        rows.extend(data)
        after = str(data[-1][0])
        if len(data) < limit:
            break
    frame = pd.DataFrame(
        [
            {
                "timestamp": _ts(row[0]),
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5]),
            }
            for row in rows
        ]
    )
    if frame.empty:
        return frame
    return frame.drop_duplicates(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)


async def fetch_okx_funding_history(
    client: httpx.AsyncClient,
    inst_id: str,
    *,
    limit: int = 200,
) -> pd.DataFrame:
    resp = await client.get(_OKX_FUNDING, params={"instId": inst_id, "limit": str(limit)}, headers=_DEFAULT_HEADERS)
    resp.raise_for_status()
    data = (resp.json() or {}).get("data") or []
    frame = pd.DataFrame(
        [{"timestamp": _ts(row["fundingTime"]), "funding_rate": float(row["fundingRate"])} for row in data]
    )
    if frame.empty:
        return frame
    return frame.drop_duplicates(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)


async def fetch_okx_open_interest_history(
    client: httpx.AsyncClient,
    inst_id: str,
    *,
    period: str = "1H",
) -> pd.DataFrame:
    resp = await client.get(
        _OKX_OPEN_INTEREST,
        params={"instId": inst_id, "period": period},
        headers=_DEFAULT_HEADERS,
    )
    resp.raise_for_status()
    data = (resp.json() or {}).get("data") or []
    frame = pd.DataFrame(
        [
            {
                "timestamp": _ts(row[0]),
                "oi_contracts": float(row[1]),
                "oi_base_ccy": float(row[2]),
                "oi_usd": float(row[3]),
            }
            for row in data
        ]
    )
    if frame.empty:
        return frame
    return frame.drop_duplicates(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)


def merge_public_derivatives_context(
    swap_candles: pd.DataFrame,
    spot_candles: pd.DataFrame,
    funding_history: pd.DataFrame,
    open_interest_history: pd.DataFrame,
) -> pd.DataFrame:
    if swap_candles.empty:
        return swap_candles.copy()
    merged = swap_candles.merge(
        spot_candles[["timestamp", "close"]].rename(columns={"close": "spot_close"}),
        on="timestamp",
        how="left",
    )
    merged["basis"] = (merged["close"] - merged["spot_close"]) / merged["spot_close"]
    merged = pd.merge_asof(merged.sort_values("timestamp"), funding_history.sort_values("timestamp"), on="timestamp", direction="backward")
    merged = pd.merge_asof(merged.sort_values("timestamp"), open_interest_history.sort_values("timestamp"), on="timestamp", direction="backward")
    merged["funding_rate"] = merged["funding_rate"].fillna(0.0)
    for column in ("oi_contracts", "oi_base_ccy", "oi_usd"):
        if column in merged:
            merged[column] = merged[column].ffill().fillna(0.0)
    merged["basis"] = merged["basis"].replace([float("inf"), float("-inf")], 0.0).fillna(0.0)
    return merged.reset_index(drop=True)
