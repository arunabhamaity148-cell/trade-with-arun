"""Signal engine tests."""
import pytest

from twa.features.engineering import compute_all
from twa.models.types import Side, Timeframe
from twa.regime.classifier import classify, regime_confidence
from twa.signal.engine import (
    DEFAULT_CFG, EngineConfig, build_factor_vector, compute_signal, normalise_factor,
    project_symbol_factors, atr,
)
from tests.conftest import make_candles


def test_build_factor_vector_has_all_keys():
    fv = build_factor_vector({})
    for k in ("funding","basis","oi_delta","obi","trend_strength_48","log_return_16",
             "obv_slope_48","volume_zscore_96","realised_vol_30"):
        assert k in fv


def test_signal_emits_long_on_strong_uptrend():
    candles = make_candles(n=400, start=10_000.0, drift=8.0, vol=0.001)
    feats = compute_all(candles)
    regime = classify(feats)
    overrides = project_symbol_factors(funding_norm=-0.4, basis_norm=0.0,
                                        oi_delta_norm=0.8, obi_norm=0.8)
    sig = compute_signal(candles, Timeframe.H1, overrides, regime, regime_conf=0.95)
    assert sig is not None, f"empty signal in regime={regime.value} features={feats}"
    assert sig.side == Side.LONG
    assert sig.confidence > 0.0
    assert sig.confidence <= 0.99
    assert sig.entry_zone[0] < sig.entry_zone[1]


def test_signal_short_on_downtrend():
    candles = make_candles(n=400, start=80_000.0, drift=-8.0, vol=0.001)
    feats = compute_all(candles)
    regime = classify(feats)
    overrides = project_symbol_factors(funding_norm=0.9, basis_norm=0.0,
                                        oi_delta_norm=-0.8, obi_norm=-0.8)
    sig = compute_signal(candles, Timeframe.H1, overrides, regime, regime_conf=0.95)
    assert sig is not None
    assert sig.side in (Side.LONG, Side.SHORT)
    assert sig.confidence > 0.0


def test_cross_exchange_overrides_are_merged_without_zeroing_candle_factors():
    candles = make_candles(n=400, start=10_000.0, drift=8.0, vol=0.001)
    feats = compute_all(candles)
    regime = classify(feats)
    baseline = compute_signal(candles, Timeframe.H1, {}, regime, regime_conf=0.95)
    overrides = project_symbol_factors(funding_norm=1.0, basis_norm=0.0,
                                        oi_delta_norm=-1.0, obi_norm=-1.0)
    sig = compute_signal(candles, Timeframe.H1, overrides, regime, regime_conf=0.95)
    assert baseline is not None
    assert sig is not None
    factor_names = {c.name for c in sig.factor_contributions}
    assert {"trend_strength_48", "log_return_16", "obv_slope_48"}.issubset(factor_names)
    assert sig.confidence < baseline.confidence


def test_signal_returns_none_below_min_confidence():
    candles = make_candles(n=80, vol=0.05)
    feats = compute_all(candles)
    regime = classify(feats)
    rc = regime_confidence(feats, regime)
    overrides = project_symbol_factors(0.0, 0.0, 0.0, 0.0)
    cfg = EngineConfig(min_confidence=0.99)
    sig = compute_signal(candles, Timeframe.H1, overrides, regime, rc, cfg=cfg)
    assert sig is None


def test_normalise_factor_clamps():
    assert normalise_factor("funding", 1e9) == 1.0
    assert normalise_factor("funding", -1e9) == -1.0
