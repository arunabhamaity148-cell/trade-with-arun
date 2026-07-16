"""Candidate feature generation and standalone predictive scoring."""
from __future__ import annotations

from typing import Dict, List

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from twa.logging import get_logger
from twa.research.lab import ResearchSession
from twa.research.utils import rank_ic, split_slices

log = get_logger("research.feature_discovery")

_BASE_COLUMNS = {"timestamp", "symbol", "open", "high", "low", "close", "volume", "regime"}


class FeatureDiscoveryRow(BaseModel):
    name: str
    ic: float
    stability: float
    subperiod_ics: List[float] = Field(default_factory=list)
    redundancy_corr: float = 0.0
    redundant_with: str = ""


class FeatureDiscoveryReport(BaseModel):
    symbol: str
    timeframe: str
    horizon: int
    rows: List[FeatureDiscoveryRow]


class FeatureDiscoveryEngine:
    """Generate, score, and rank candidate features for a research session."""

    def __init__(self, horizon: int = 4, subperiods: int = 3):
        self.horizon = horizon
        self.subperiods = subperiods

    def discover(self, session: ResearchSession) -> FeatureDiscoveryReport:
        target = session.target_frame(self.horizon)
        candidates = self._candidate_frame(session)
        joined = target[["timestamp", "forward_return"]].merge(candidates, on="timestamp", how="inner")
        prod = target.drop(columns=["forward_return", "forward_return_bps"], errors="ignore")
        prod_features = [c for c in prod.columns if c not in _BASE_COLUMNS]
        rows: List[FeatureDiscoveryRow] = []
        for name in [c for c in joined.columns if c not in {"timestamp", "forward_return"}]:
            ic = rank_ic(joined[name], joined["forward_return"])
            sub_ics = []
            for slc in split_slices(len(joined), self.subperiods):
                piece = joined.iloc[slc]
                sub_ics.append(rank_ic(piece[name], piece["forward_return"]))
            stability = float(1.0 / (1.0 + np.std(sub_ics or [0.0])))
            redundancy_corr = 0.0
            redundant_with = ""
            aligned = prod.merge(joined[["timestamp", name]], on="timestamp", how="inner")
            for prod_name in prod_features:
                corr = aligned[[prod_name, name]].corr().iloc[0, 1] if len(aligned) >= 8 else 0.0
                corr = 0.0 if np.isnan(corr) else float(abs(corr))
                if corr > redundancy_corr:
                    redundancy_corr = corr
                    redundant_with = prod_name
            rows.append(FeatureDiscoveryRow(
                name=name,
                ic=float(ic),
                stability=stability,
                subperiod_ics=[float(v) for v in sub_ics],
                redundancy_corr=float(redundancy_corr),
                redundant_with=redundant_with,
            ))
        rows.sort(key=lambda r: (abs(r.ic), r.stability), reverse=True)
        log.info("research.feature_discovery.complete", symbol=session.symbol, rows=len(rows))
        return FeatureDiscoveryReport(symbol=session.symbol, timeframe=session.timeframe.value, horizon=self.horizon, rows=rows)

    def _candidate_frame(self, session: ResearchSession) -> pd.DataFrame:
        df = session.frame.copy().reset_index(drop=True)
        close = df["close"]
        volume = df["volume"]
        high = df["high"]
        low = df["low"]
        ret = np.log(close).diff()
        out = pd.DataFrame({
            "timestamp": df["timestamp"],
            "ret_1": ret,
            "ret_3": np.log(close / close.shift(3)),
            "ret_8": np.log(close / close.shift(8)),
            "mean_rev_8": close / close.rolling(8).mean() - 1.0,
            "momentum_24": close / close.shift(24) - 1.0,
            "vol_8": ret.rolling(8).std(),
            "vol_24": ret.rolling(24).std(),
            "range_pct_8": ((high - low) / close).rolling(8).mean(),
            "volume_ratio_8": volume / volume.rolling(8).mean(),
            "volume_trend_16": volume.ewm(span=16, adjust=False).mean().pct_change(),
            "wick_balance_8": (((high - close) - (close - low)) / close).rolling(8).mean(),
            "breakout_distance_20": close / high.rolling(20).max() - 1.0,
            "compression_20": ((high.rolling(20).max() - low.rolling(20).min()) / close).replace([np.inf, -np.inf], np.nan),
        })
        return out.dropna().reset_index(drop=True)
