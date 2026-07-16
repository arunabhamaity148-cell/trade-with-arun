"""Risk engine tests."""
import pytest

from twa.config import Settings
from twa.models.types import Side, RegimeLabel, SignalIdea, Timeframe
from twa.risk.engine import CooldownBook, RiskEngine
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from signals_factory import make_signal  # noqa: E402  (test helper)


def test_cooldown_blocks_repeat():
    cd = CooldownBook()
    cd.mark("BTCUSDT|1h|LONG")
    assert not cd.is_cool("BTCUSDT|1h|LONG", cooldown_s=900)


def test_risk_accepts_strong_signal(monkeypatch):
    monkeypatch.setenv("TWA_RISK_COOLDOWN_S", "0")
    s = Settings(_env_file=None)
    risk = RiskEngine(s)
    cand = make_signal(confidence=0.6, side=Side.LONG, regime=RegimeLabel.TREND_UP)
    v = risk.evaluate(cand, news_dampen=1.0, ml_calibration=1.0,
                      high_volatility=False, stressed_regime=False)
    assert v.accepted
    assert v.adjusted_confidence >= 0.2


def test_risk_rejects_low_calibrated_confidence():
    s = Settings(_env_file=None)
    risk = RiskEngine(s)
    cand = make_signal(confidence=0.3, side=Side.LONG)
    v = risk.evaluate(cand, news_dampen=1.0, ml_calibration=0.01,
                      high_volatility=False, stressed_regime=False)
    assert not v.accepted
    assert "confidence" in v.reason.lower() or "calibrated" in v.reason


def test_risk_caps_confidence_in_stress():
    s = Settings(_env_file=None)
    risk = RiskEngine(s)
    cand = make_signal(confidence=0.9, side=Side.LONG)
    v = risk.evaluate(cand, news_dampen=1.0, ml_calibration=1.0,
                      high_volatility=False, stressed_regime=True)
    assert v.adjusted_confidence <= 0.36


def test_risk_dampens_in_high_volatility():
    s = Settings(_env_file=None)
    risk = RiskEngine(s)
    cand = make_signal(confidence=0.8, side=Side.LONG)
    v = risk.evaluate(cand, news_dampen=1.0, ml_calibration=1.0,
                      high_volatility=True, stressed_regime=False)
    # base 0.8 × 0.75 ≈ 0.6
    assert 0.5 <= v.adjusted_confidence <= 0.72
