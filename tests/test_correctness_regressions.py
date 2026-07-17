"""High-priority correctness regressions from production audit."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from twa.config import Settings
from twa.models.types import FundingRate, OpenInterest, OrderBook, OrderBookLevel, RegimeLabel, Ticker, Timeframe
from twa.orchestration.engine import Orchestrator
from twa.risk import RiskEngine
from twa.signal.engine import DEFAULT_CFG, EngineConfig, compute_signal, project_symbol_factors
from tests.conftest import make_candles


def test_only_one_risk_engine_module_exists():
    import importlib
    import twa.risk as risk_pkg

    engine_mod = importlib.import_module("twa.risk.engine")
    assert hasattr(engine_mod, "RiskEngine")
    assert risk_pkg.RiskEngine is engine_mod.RiskEngine
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("twa.risk.risk_engine")


def test_signal_confidence_is_raw_before_risk_and_ml(monkeypatch):
    candles = make_candles(n=240, drift=2.0, vol=0.001)
    overrides = project_symbol_factors(0.1, 0.0, 0.2, 0.2)
    sig = compute_signal(candles, Timeframe.H1, overrides, RegimeLabel.TREND_UP, regime_conf=0.9)
    assert sig is not None
    risk = RiskEngine(Settings(_env_file=None, risk_cooldown_s=0))
    verdict = risk.evaluate(sig, news_dampen=0.8, ml_calibration=0.5, high_volatility=False, stressed_regime=False)
    expected = min(0.95, sig.raw_confidence * 0.8 * 0.5)
    assert verdict.adjusted_confidence == pytest.approx(expected, rel=1e-6)


@pytest.mark.asyncio
async def test_orchestrator_passes_real_raw_confidence_to_calibrator(monkeypatch):
    class FakeAggregator:
        def __init__(self, settings):
            self.settings = settings
            self.adapters = {}

        async def fetch_candles(self, symbol, timeframe, limit=500):
            return make_candles(n=240, drift=1.5, vol=0.001, timeframe=timeframe, symbol=symbol)

        async def fetch_funding(self, symbol):
            return FundingRate(symbol=symbol, exchange="test", rate=0.0001)

        async def fetch_open_interest(self, symbol):
            return OpenInterest(symbol=symbol, exchange="test", open_interest=110.0)

        async def fetch_orderbook(self, symbol, depth=20):
            bids = [OrderBookLevel(price=100 - i, size=1.0) for i in range(depth)]
            asks = [OrderBookLevel(price=101 + i, size=1.0) for i in range(depth)]
            return OrderBook(symbol=symbol, exchange="test", bids=bids, asks=asks)

        async def fetch_ticker(self, symbol):
            return None

        async def close(self):
            return None

    seen = {}

    class RecordingCalibrator:
        def load(self):
            return None

        def calibrate(self, raw_confidence: float) -> float:
            seen["arg"] = raw_confidence
            return 1.0

    orch = Orchestrator(Settings(_env_file=None, symbols=["BTCUSDT"], risk_cooldown_s=0))
    orch.data = FakeAggregator(orch.settings)
    orch.calibrator = RecordingCalibrator()
    sig = await orch._one_symbol("BTCUSDT")
    assert sig is not None
    assert seen["arg"] == pytest.approx(sig.raw_confidence, rel=1e-6)


@pytest.mark.asyncio
async def test_orchestrator_computes_real_basis_and_oi_delta():
    class SpotAdapter:
        async def fetch_ticker(self, symbol):
            return Ticker(symbol=symbol, exchange="coinbase", bid=100.0, ask=100.0, last=100.0, volume_24h=0.0, change_pct_24h=0.0)

    class PerpAdapter:
        async def fetch_ticker(self, symbol):
            return Ticker(symbol=symbol, exchange="binance", bid=101.0, ask=101.0, last=101.0, volume_24h=0.0, change_pct_24h=0.0)

    class FakeAggregator:
        def __init__(self, settings):
            self.settings = settings
            self.adapters = {"coinbase": SpotAdapter(), "binance": PerpAdapter()}
            self._oi = 100.0

        async def fetch_candles(self, symbol, timeframe, limit=500):
            return make_candles(n=240, drift=1.5, vol=0.001, timeframe=timeframe, symbol=symbol)

        async def fetch_funding(self, symbol):
            return FundingRate(symbol=symbol, exchange="binance", rate=0.0001)

        async def fetch_open_interest(self, symbol):
            self._oi += 10.0
            return OpenInterest(symbol=symbol, exchange="binance", open_interest=self._oi)

        async def fetch_orderbook(self, symbol, depth=20):
            bids = [OrderBookLevel(price=100 - i, size=2.0) for i in range(depth)]
            asks = [OrderBookLevel(price=101 + i, size=1.0) for i in range(depth)]
            return OrderBook(symbol=symbol, exchange="binance", bids=bids, asks=asks)

        async def fetch_ticker(self, symbol):
            return None

        async def close(self):
            return None

    orch = Orchestrator(Settings(_env_file=None, symbols=["BTCUSDT"], risk_cooldown_s=0))
    orch.data = FakeAggregator(orch.settings)
    first = await orch._one_symbol("BTCUSDT")
    second = await orch._one_symbol("BTCUSDT")
    assert first is not None and second is not None
    assert second.basis == pytest.approx(0.01, abs=1e-6)
    assert second.oi_delta > 0.0


def test_default_targets_are_true_one_two_three_r():
    risk_r = [target / DEFAULT_CFG.invalidation_atr for target in DEFAULT_CFG.risk_reward_targets]
    assert risk_r == pytest.approx([1.0, 2.0, 3.0])
