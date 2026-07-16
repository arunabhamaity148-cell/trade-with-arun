"""Input feature distribution drift detection."""
from __future__ import annotations

from typing import List, Optional

import pandas as pd
from pydantic import BaseModel, Field
from scipy.stats import ks_2samp

from twa.research.utils import population_stability_index

_BASE_COLUMNS = {"timestamp", "symbol", "open", "high", "low", "close", "volume", "regime", "forward_return", "forward_return_bps"}


class FeatureDriftRow(BaseModel):
    feature: str
    psi: float
    ks_stat: float
    ks_pvalue: float
    drifted: bool


class FeatureDriftReport(BaseModel):
    rows: List[FeatureDriftRow] = Field(default_factory=list)
    drifted_features: List[str] = Field(default_factory=list)


class FeatureDriftDetector:
    """Compare baseline and recent feature distributions."""

    def detect(
        self,
        frame: pd.DataFrame,
        feature_names: Optional[List[str]] = None,
        *,
        baseline_frac: float = 0.7,
        psi_threshold: float = 0.20,
        ks_pvalue_threshold: float = 0.05,
    ) -> FeatureDriftReport:
        df = frame.select_dtypes(include=["number"]).copy()
        if feature_names is None:
            feature_names = [c for c in df.columns if c not in _BASE_COLUMNS]
        split = max(1, int(len(df) * baseline_frac))
        baseline = df.iloc[:split]
        recent = df.iloc[split:]
        rows: List[FeatureDriftRow] = []
        for name in feature_names:
            if name not in df:
                continue
            psi = population_stability_index(baseline[name], recent[name])
            ks = ks_2samp(baseline[name].dropna(), recent[name].dropna())
            drifted = bool(psi >= psi_threshold or ks.pvalue <= ks_pvalue_threshold)
            rows.append(FeatureDriftRow(
                feature=name,
                psi=float(psi),
                ks_stat=float(ks.statistic),
                ks_pvalue=float(ks.pvalue),
                drifted=drifted,
            ))
        rows.sort(key=lambda r: (r.drifted, r.psi, r.ks_stat), reverse=True)
        return FeatureDriftReport(rows=rows, drifted_features=[r.feature for r in rows if r.drifted])
