"""Training pipeline for the production confidence calibrator."""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from twa.config import Settings
from twa.logging import get_logger
from twa.research.utils import ensure_research_dir, load_jsonl

log = get_logger("research.calibration")


class CalibrationMetrics(BaseModel):
    brier_score: float
    ece: float
    reliability_bins: List[Dict[str, float]] = Field(default_factory=list)


class CalibrationReport(BaseModel):
    model_path: str
    method: str
    rows_used: int
    metrics: CalibrationMetrics
    drift_summary: str = ""


class ProbabilityCalibratorModel:
    """Joblib-serialisable wrapper with a sklearn-like `predict_proba` API."""

    def __init__(self, method: str, model):
        self.method = method
        self.model = model

    def predict_proba(self, x):
        arr = np.asarray(x, dtype=float).reshape(-1)
        if self.method == "isotonic":
            probs = np.clip(self.model.predict(arr), 0.001, 0.999)
        else:
            probs = np.clip(self.model.predict_proba(arr.reshape(-1, 1))[:, 1], 0.001, 0.999)
        return np.column_stack([1.0 - probs, probs])


class CalibrationPipeline:
    """Fit and persist a confidence→win-rate calibration model."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def fit_from_signal_log(self, path: Path, *, method: str = "isotonic") -> CalibrationReport:
        df = load_jsonl(path)
        return self.fit_frame(df, method=method)

    def fit_out_of_fold(self, frame: pd.DataFrame, *, prediction_col: str = "prediction", target_col: str = "target", method: str = "isotonic") -> CalibrationReport:
        df = frame.copy()
        if prediction_col not in df or target_col not in df:
            raise ValueError("out-of-fold frame must contain prediction and target columns")
        df = df[[prediction_col, target_col]].dropna().copy()
        df["prediction"] = df[prediction_col].astype(float).abs().clip(0.001, 0.999)
        df["outcome"] = (df[target_col].astype(float) > 0).astype(float)
        return self.fit_frame(df[["prediction", "outcome"]].rename(columns={"prediction": "raw_confidence"}), method=method)

    def fit_frame(self, frame: pd.DataFrame, *, method: str = "isotonic") -> CalibrationReport:
        conf_col = "raw_confidence" if "raw_confidence" in frame else ("confidence" if "confidence" in frame else None)
        outcome_col = "realized_outcome" if "realized_outcome" in frame else ("outcome" if "outcome" in frame else None)
        if conf_col is None or outcome_col is None:
            raise ValueError("frame must contain confidence/raw_confidence and outcome/realized_outcome columns")
        df = frame[[conf_col, outcome_col]].dropna().copy()
        if df.empty:
            raise ValueError("no calibration rows after dropping nulls")
        x = df[conf_col].astype(float).to_numpy()
        y = df[outcome_col].astype(float).to_numpy()
        model = self._fit_model(x, y, method)
        probs = model.predict_proba(x.reshape(-1, 1))[:, 1]
        metrics = self._metrics(x, y, probs)
        out_dir = self.settings.ml_model_path.parent
        out_dir.mkdir(parents=True, exist_ok=True)
        import joblib  # type: ignore
        joblib.dump(model, self.settings.ml_model_path)
        report = CalibrationReport(
            model_path=str(self.settings.ml_model_path),
            method=method,
            rows_used=int(len(df)),
            metrics=metrics,
            drift_summary=self._drift_summary(metrics),
        )
        report_dir = ensure_research_dir(self.settings, "calibration")
        (report_dir / "latest_report.json").write_text(report.model_dump_json(indent=2), encoding="utf-8")
        log.info("research.calibration.saved", path=str(self.settings.ml_model_path), rows=len(df))
        return report

    def _fit_model(self, x: np.ndarray, y: np.ndarray, method: str) -> ProbabilityCalibratorModel:
        if method == "isotonic":
            from sklearn.isotonic import IsotonicRegression
            fitted = IsotonicRegression(out_of_bounds="clip").fit(x, y)
            return ProbabilityCalibratorModel("isotonic", fitted)
        from sklearn.linear_model import LogisticRegression
        fitted = LogisticRegression(random_state=42).fit(x.reshape(-1, 1), y)
        return ProbabilityCalibratorModel("platt", fitted)

    def _metrics(self, x: np.ndarray, y: np.ndarray, probs: np.ndarray, bins: int = 10) -> CalibrationMetrics:
        brier = float(np.mean((probs - y) ** 2))
        edges = np.linspace(0.0, 1.0, bins + 1)
        details: List[Dict[str, float]] = []
        ece = 0.0
        for left, right in zip(edges[:-1], edges[1:]):
            mask = (x >= left) & (x <= right if right == 1.0 else x < right)
            if not mask.any():
                continue
            conf_mean = float(x[mask].mean())
            hit_rate = float(y[mask].mean())
            weight = float(mask.mean())
            ece += abs(conf_mean - hit_rate) * weight
            details.append({
                "bin_left": float(left),
                "bin_right": float(right),
                "count": float(mask.sum()),
                "avg_confidence": conf_mean,
                "realized_rate": hit_rate,
            })
        return CalibrationMetrics(brier_score=brier, ece=float(ece), reliability_bins=details)

    def _drift_summary(self, metrics: CalibrationMetrics) -> str:
        if not metrics.reliability_bins:
            return "No reliability bins available."
        largest_gap = max((abs(row["avg_confidence"] - row["realized_rate"]), row) for row in metrics.reliability_bins)
        gap, row = largest_gap
        if gap <= 0.05:
            return "Calibration is stable; predicted confidence and realized hit rate stay closely aligned across bins."
        direction = "over-confident" if row["avg_confidence"] > row["realized_rate"] else "under-confident"
        return (
            f"Largest calibration drift appears in {row['bin_left']:.1f}-{row['bin_right']:.1f} confidence: "
            f"the model is {direction} by about {gap:.2f}."
        )
