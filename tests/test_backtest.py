"""Backtest honesty tests."""
import pytest
from datetime import datetime

from twa.backtest.replay import BacktestResult, TradeRecord, monte_carlo, simulate
from twa.models.types import Timeframe


def test_simulate_marks_insufficient_when_short():
    from tests.conftest import make_candles
    candles = make_candles(n=20)
    result = simulate(candles, "1h", factor_overrides_list=[{}] * len(candles))
    assert result.note in ("INSUFFICIENT_DATA", "INSUFFICIENT_TRADES")


def test_simulate_emits_trades_and_marks():
    from tests.conftest import make_candles
    candles = make_candles(n=300, drift=4.0, vol=0.001)
    result = simulate(candles, "1h", factor_overrides_list=[{}] * len(candles))
    assert isinstance(result, BacktestResult)
    if result.total_trades > 0:
        for t in result.trades[:5]:
            assert t.symbol == "BTCUSDT"
            assert t.entry_price > 0


def test_monte_carlo_returns_insufficient_when_short():
    trades = []
    out = monte_carlo(trades)
    assert out["note"] == "INSUFFICIENT_TRADES"


def test_summary_reports_win_rate_only_when_enough():
    r = BacktestResult(window_start=datetime.utcnow(), window_end=datetime.utcnow())
    assert r.win_rate() is None
    r.trades = [
        TradeRecord(symbol="BTCUSDT", timeframe="1h", side=__import__(
            "twa.models.types", fromlist=["Side"]).Side.LONG,
            entry_time=datetime.utcnow(), entry_price=100.0,
            invalidation=99.0, targets=[101.0],
            confidence=0.5, regime=__import__("twa.models.types",
            fromlist=["RegimeLabel"]).RegimeLabel.TREND_UP,
            exit_time=datetime.utcnow(), exit_price=101.0,
            exit_reason="target_1R", pnl_bps=100.0,
            mfe_bps=120.0, mae_bps=-10.0, holding_bars=8)
        for _ in range(31)
    ]
    # With ≥ 30 trades, win rate must be defined.
    assert r.win_rate() is not None
