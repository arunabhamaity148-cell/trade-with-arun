"""Sandbox for comparing regime classifiers and regime-conditional edge."""
from __future__ import annotations

from typing import List

import numpy as np
from pydantic import BaseModel, Field

from twa.regime.classifier import RegimeConfig, classify
from twa.research.lab import ResearchSession

_BASE_FEATURES = [
    "log_return_16",
    "realised_vol_30",
    "trend_strength_48",
    "relative_range_48",
    "return_kurt_64",
]


class RegimeVariant(BaseModel):
    name: str
    vol_volatile: float = 0.85
    vol_stressed: float = 1.30
    vol_range_max: float = 0.45
    trend_strong: float = 0.55
    range_strong: float = 0.20
    kurt_stressed: float = 6.0

    def to_config(self) -> RegimeConfig:
        return RegimeConfig(
            vol_volatile=self.vol_volatile,
            vol_stressed=self.vol_stressed,
            vol_range_max=self.vol_range_max,
            trend_strong=self.trend_strong,
            range_strong=self.range_strong,
            kurt_stressed=self.kurt_stressed,
        )


class RegimeLabRow(BaseModel):
    variant: str
    regime: str
    sample_count: int
    mean_edge_bps: float
    positive_rate: float


class RegimeLabReport(BaseModel):
    rows: List[RegimeLabRow] = Field(default_factory=list)
    best_variant: str = ""


class RegimeLaboratory:
    """Evaluate regime-conditional edge across classifier variants."""

    def compare(self, session: ResearchSession, variants: List[RegimeVariant] | None = None, *, horizon: int = 4) -> RegimeLabReport:
        variants = variants or [
            RegimeVariant(name="production"),
            RegimeVariant(name="trend_sensitive", trend_strong=0.45),
            RegimeVariant(name="stress_sensitive", vol_stressed=1.10, kurt_stressed=4.5),
        ]
        df = session.target_frame(horizon)
        rows: List[RegimeLabRow] = []
        best_variant = ""
        best_edge = -float("inf")
        for variant in variants:
            cfg = variant.to_config()
            regime_labels = []
            for _, row in df.iterrows():
                features = {name: float(row.get(name, 0.0)) for name in _BASE_FEATURES}
                regime_labels.append(classify(features, cfg=cfg).value)
            work = df.copy()
            work["variant_regime"] = regime_labels
            work["signal_edge_bps"] = np.sign(work["log_return_16"]).replace(0, 1.0) * work["forward_return_bps"]
            variant_edge = float(work["signal_edge_bps"].mean()) if len(work) else 0.0
            if variant_edge > best_edge:
                best_edge = variant_edge
                best_variant = variant.name
            for regime, grp in work.groupby("variant_regime"):
                rows.append(RegimeLabRow(
                    variant=variant.name,
                    regime=str(regime),
                    sample_count=int(len(grp)),
                    mean_edge_bps=float(grp["signal_edge_bps"].mean()) if len(grp) else 0.0,
                    positive_rate=float((grp["signal_edge_bps"] > 0).mean()) if len(grp) else 0.0,
                ))
        rows.sort(key=lambda r: (r.variant, r.regime))
        return RegimeLabReport(rows=rows, best_variant=best_variant)
