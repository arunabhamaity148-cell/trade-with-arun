"""Regression tests for research/backtest integrity fixes."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

from twa.backtest.replay import INTRABAR_CONFLICT_RESOLUTION, _realise, simulate
from twa.config import Settings
from twa.models.types import Candle, Timeframe
from twa.research.benchmarking import BenchmarkRunner, PRODUCTION_ENGINE_TECHNICAL_ONLY
from twa.research.edge_validation import EdgeValidationFramework, ThresholdStrategy
from twa.research.lab import ResearchSession
from tests.conftest import make_candles
from tests.signals_factory import make_signal


def test_benchmark_relabels_technical_only_production_row():
    settings = Settings(_env_file=None)
    candles = make_candles(n=180)
    session = ResearchSession.from_candles(settings, "BTCUSDT", Timeframe.H1, candles)
    runner = BenchmarkRunner(settings)
    row = runner._production_engine(session)
    assert row.name == PRODUCTION_ENGINE_TECHNICAL_ONLY


def test_simulate_applies_risk_gate_and_drops_trade_rate(monkeypatch):
    candles = make_candles(n=140, drift=1.0, vol=0.0005)

    def fake_compute_signal(*args, **kwargs):
        return make_signal(confidence=0.6, timeframe=Timeframe.H1)

    monkeypatch.setattr("twa.backtest.replay.compute_signal", fake_compute_signal)

    loose = simulate(
        candles,
        Timeframe.H1,
        factor_overrides_list=[{}] * len(candles),
        settings=Settings(_env_file=None, risk_cooldown_s=0),
        max_active_signals=1000,
    )
    gated = simulate(
        candles,
        Timeframe.H1,
        factor_overrides_list=[{}] * len(candles),
        settings=Settings(_env_file=None, risk_cooldown_s=24 * 3600),
        max_active_signals=1000,
    )
    assert loose.total_trades > gated.total_trades
    assert gated.total_trades <= 3


def test_simulate_respects_symbol_side_cooldown(monkeypatch):
    candles = make_candles(n=90, drift=0.5, vol=0.0001)

    def fake_compute_signal(*args, **kwargs):
        return make_signal(confidence=0.6, timeframe=Timeframe.H1)

    monkeypatch.setattr("twa.backtest.replay.compute_signal", fake_compute_signal)
    result = simulate(
        candles,
        Timeframe.H1,
        factor_overrides_list=[{}] * len(candles),
        settings=Settings(_env_file=None, risk_cooldown_s=3 * 3600),
        max_active_signals=1000,
    )
    assert result.total_trades == 5  # bars 60,63,66,69,72; intervening bars are blocked


def test_zero_threshold_sensitivity_uses_additive_perturbation():
    settings = Settings(_env_file=None)
    session = ResearchSession.from_candles(settings, "BTCUSDT", Timeframe.H1, make_candles(n=120))
    session.feature_frame = pd.DataFrame(
        {
            "timestamp": [datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(hours=i) for i in range(6)],
            "symbol": ["BTCUSDT"] * 6,
            "close": [100, 101, 102, 103, 104, 105],
            "signal": [-0.20, -0.05, 0.02, 0.04, 0.12, 0.20],
        }
    )
    framework = EdgeValidationFramework()
    strategy = ThresholdStrategy(
        name="zero_threshold",
        feature_name="signal",
        threshold=0.0,
        direction="above",
        trade_side="long",
        horizon=1,
        sensitivity_pct=0.10,
    )
    sensitivity = framework._sensitivity(session, strategy)
    assert set(sensitivity) == {"threshold_abs_-0.10", "threshold_abs_+0.10"}
    assert sensitivity["threshold_abs_-0.10"] != sensitivity["threshold_abs_+0.10"]


def test_intrabar_conflict_resolution_is_explicitly_stop_first():
    sig = make_signal(confidence=0.7)
    future = [
        Candle(
            symbol="BTCUSDT",
            exchange="test",
            timeframe=Timeframe.H1,
            open_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
            close_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
            open=100.0,
            high=103.0,
            low=98.5,
            close=101.0,
            volume=1000.0,
        )
    ]
    trade = _realise(sig, future)
    assert INTRABAR_CONFLICT_RESOLUTION == "stop_first"
    assert trade.exit_reason == "invalidation"
    assert trade.exit_price == trade.invalidation
    assert trade.invalidation != sig.invalidation
