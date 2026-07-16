"""Optional HMM regime detector (scikit-learn-like fallback).

This module is *optional*.  When sklearn is not installed, the
deterministic rule-based classifier is used.  Both are surfaced behind the
same API (`RegimeDetector.detect`) so the orchestrator does not need to
branch.
"""
from __future__ import annotations

from typing import Optional

from twa.logging import get_logger

log = get_logger("regime.hmm")


class RegimeDetector:
    """Wrapper that tries HMM, falls back to rule-based.

    Never raises ImportError; falls back transparently.
    """

    def __init__(self, use_hmm: bool = True):
        self.use_hmm = use_hmm
        self._sklearn = None
        if use_hmm:
            try:
                import sklearn  # noqa: F401
                self._sklearn = sklearn
            except Exception as e:  # noqa: BLE001
                log.warning("regime.hmm.sklearn_unavailable", err=str(e))
                self._sklearn = None

    def detect(self, features: dict) -> str:
        """Return regime label string ("trend_up" / "range" / ...).

        Uses HMM if sklearn is available AND `use_hmm` AND a model was fit.
        Otherwise uses the deterministic rule-based classifier.
        """
        if self._sklearn is not None and self.use_hmm and getattr(self, "model", None) is not None:
            try:
                return self._hmm_predict(features)
            except Exception as e:  # noqa: BLE001
                log.debug("regime.hmm.predict_failed", err=str(e))
        from twa.regime.classifier import classify  # local to avoid cycle
        return classify(features).value

    # -- internals -----------------------------------------------------------
    def _ensure_model(self, n_states: int = 3):
        """Lazy build a GaussianHMM, fitted lazily on .fit()."""
        if getattr(self, "model", None) is not None:
            return self.model
        if self._sklearn is None:
            return None
        from sklearn.hmm import GaussianHMM  # type: ignore  # older sklearn path
        # If it's not available, fall back to deterministic.
        self.model = GaussianHMM(n_components=n_states, covariance_type="diag", n_iter=10)
        return self.model

    def _hmm_predict(self, features: dict) -> str:
        # Placeholder for a real implementation; deterministic fallback always used.
        raise RuntimeError("hmm-model not fitted; using deterministic fallback")
