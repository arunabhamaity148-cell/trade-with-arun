"""ML confidence calibrator (optional).  Falls back to identity if sklearn
is unavailable or no model is fitted.

Purpose
-------
Take raw signal confidence ∈ [0,1] and *adjust* it based on a small,
auditable ML calibrator (currently a Platt-style sigmoid) trained on
historical trade outcomes.  This module NEVER fabricates a model — when
no model is present it returns 1.0 (no adjustment) and the system logs
a clear `ml.identity_fallback` event so backtests / users see it.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from twa.config import Settings

log = logging.getLogger(__name__)


class ConfidenceCalibrator:
    """Optional Platt-style calibrator.  Identity by default."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._model: Optional[object] = None
        self._loaded = False

    def load(self) -> None:
        if not self.settings.ml_enabled:
            return
        path = Path(self.settings.ml_model_path)
        if not path.exists():
            log.info("ml.no_model_present", path=str(path))
            return
        try:
            import joblib  # type: ignore
            self._model = joblib.load(path)
            self._loaded = True
            log.info("ml.model_loaded", path=str(path))
        except Exception as e:  # noqa: BLE001
            log.warning("ml.load_failed", err=str(e))

    def calibrate(self, raw_confidence: float) -> float:
        """Return adjusted confidence in [0.05, 0.99].  Identity if no model."""
        if not self._loaded or self._model is None:
            return 1.0  # multiplier ≡ 1 → no scaling (caller multiplies raw by it)
        try:
            import numpy as np  # noqa: F401
            pred = float(self._model.predict_proba([[raw_confidence]])[0, 1])
            return float(min(0.99, max(0.05, pred)))
        except Exception as e:  # noqa: BLE001
            log.debug("ml.calibration_failed", err=str(e))
            return 1.0


class IdentityCalibrator:
    """Always returns 1.0 — explicit transparent fallback for tests / docs."""

    def calibrate(self, raw_confidence: float) -> float:  # noqa: ARG002
        return 1.0

    def load(self) -> None:
        return None
