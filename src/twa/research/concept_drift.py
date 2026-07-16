"""Concept-drift detection for feature→return relationships."""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from twa.research.lab import ResearchSession
from twa.research.utils import load_jsonl, rank_ic

_BASE_COLUMNS = {"timestamp", "symbol", "open", "high", "low", "close", "volume", "regime", "forward_return", "forward_return_bps"}


class ConceptDriftRow(BaseModel):
    feature: str
    baseline_ic: float
    recent_ic: float
    delta_ic: float
    drifted: bool


class ConceptDriftReport(BaseModel):
    rows: List[ConceptDriftRow] = Field(default_factory=list)
    page_hinkley_stat: float = 0.0
    drift_detected: bool = False
    signal_log_summary: Dict[str, float] = Field(default_factory=dict)


class ConceptDriftDetector:
    """Detect degradation in predictive relationships rather than raw feature shifts."""

    def detect(
        self,
        session: ResearchSession,
        *,
        horizon: int = 4,
        feature_names: Optional[List[str]] = None,
        baseline_frac: float = 0.7,
        recent_frac: float = 0.2,
    ) -> ConceptDriftReport:
        df = session.target_frame(horizon)
        if feature_names is None:
            feature_names = [c for c in df.columns if c not in _BASE_COLUMNS]
        base_end = max(8, int(len(df) * baseline_frac))
        recent_len = max(8, int(len(df) * recent_frac))
        baseline = df.iloc[:base_end]
        recent = df.iloc[-recent_len:]
        rows: List[ConceptDriftRow] = []
        ic_series: List[float] = []
        for name in feature_names:
            if name not in df:
                continue
            baseline_ic = rank_ic(baseline[name], baseline["forward_return"])
            recent_ic = rank_ic(recent[name], recent["forward_return"])
            delta = recent_ic - baseline_ic
            drifted = bool(np.sign(baseline_ic) != np.sign(recent_ic) or abs(delta) >= 0.10)
            rows.append(ConceptDriftRow(
                feature=name,
                baseline_ic=float(baseline_ic),
                recent_ic=float(recent_ic),
                delta_ic=float(delta),
                drifted=drifted,
            ))
            ic_series.append(recent_ic)
        ph = _page_hinkley(np.asarray(ic_series, dtype=float))
        return ConceptDriftReport(
            rows=rows,
            page_hinkley_stat=float(ph),
            drift_detected=bool(any(r.drifted for r in rows) or ph > 0.15),
        )

    def analyze_signal_log(self, path: Path) -> Dict[str, float]:
        df = load_jsonl(path)
        if df.empty:
            return {"rows": 0.0}
        conf_col = "raw_confidence" if "raw_confidence" in df else ("confidence" if "confidence" in df else None)
        outcome_col = "realized_outcome" if "realized_outcome" in df else ("outcome" if "outcome" in df else None)
        if conf_col is None or outcome_col is None:
            return {"rows": float(len(df)), "note": 1.0}
        residual = df[outcome_col].astype(float) - df[conf_col].astype(float)
        split = max(8, int(len(residual) * 0.7))
        baseline = residual.iloc[:split]
        recent = residual.iloc[split:]
        return {
            "rows": float(len(df)),
            "baseline_mean_residual": float(baseline.mean()),
            "recent_mean_residual": float(recent.mean()) if len(recent) else 0.0,
            "drift_score": float(abs(recent.mean() - baseline.mean())) if len(recent) else 0.0,
        }


def _page_hinkley(values: np.ndarray, delta: float = 0.01) -> float:
    if values.size == 0:
        return 0.0
    mean = 0.0
    cumulative = 0.0
    min_cumulative = 0.0
    stat = 0.0
    for idx, value in enumerate(values, start=1):
        mean += (value - mean) / idx
        cumulative += value - mean - delta
        min_cumulative = min(min_cumulative, cumulative)
        stat = max(stat, cumulative - min_cumulative)
    return float(max(0.0, stat))
