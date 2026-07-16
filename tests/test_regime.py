"""Regime classification tests."""
import pytest

from twa.features.engineering import compute_all
from twa.regime.classifier import (
    DEFAULT_CONFIG, assign_weights, classify, regime_confidence,
)
from twa.regime.hmm import RegimeDetector
from twa.models.types import RegimeLabel


def test_classify_returns_valid_label(synthetic_candles):
    feats = compute_all(synthetic_candles)
    label = classify(feats, DEFAULT_CONFIG)
    assert isinstance(label, RegimeLabel)
    assert label in (
        RegimeLabel.TREND_UP, RegimeLabel.TREND_DOWN,
        RegimeLabel.RANGE, RegimeLabel.VOLATILE, RegimeLabel.STRESSED,
    )


def test_regime_confidence_in_unit_interval():
    feats = compute_all(make_candles_drift())
    label = classify(feats)
    c = regime_confidence(feats, label)
    assert 0.0 <= c <= 0.96


def test_assign_weights_sum_to_one():
    for r in RegimeLabel:
        w = assign_weights(r)
        total = sum(abs(v) for v in w.values())
        assert 0.99 <= total <= 1.01, f"weights not normalised for {r}: total={total}"


def test_hmm_detector_falls_back_to_deterministic():
    det = RegimeDetector(use_hmm=True)  # sklearn not installed in CI by default
    label = det.detect({})
    assert label in {r.value for r in RegimeLabel}


# helper:
def make_candles_drift():
    from tests.conftest import make_candles
    return make_candles(n=300, drift=1.0, vol=0.005)
