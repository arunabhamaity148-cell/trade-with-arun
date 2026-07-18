"""Regression coverage for production-audit fixes."""
from __future__ import annotations

import pytest

from twa.config import Settings
from twa.models.types import FundingRate, OpenInterest, OrderBook, OrderBookLevel, SignalEntryState, SignalLifecycleState, Side, Timeframe
from twa.research.benchmarking import (
    BenchmarkRunner,
    ProductionVariant,
    PRODUCTION_ENGINE_NO_NEWS_GUARD,
    PRODUCTION_ENGINE_TECHNICAL_ONLY,
    PRODUCTION_ENGINE_WITH_NEWS_GUARD,
)
from twa.research.lab import ResearchSession
from twa.research.walk_forward import WalkForwardConfig
from twa.risk.engine import RiskEngine
from twa.signal.lifecycle import LiveSignalState, SignalLifecycleManager
from twa.signal.store import SignalOutcomeStore
from tests.conftest import make_candles
from tests.signals_factory import make_signal


class SilentTelegram:
    async def send_signal(self, sig):  # noqa: ARG002
        return True

    async def send_text(self, text):  # noqa: ARG002
        return True


def _wf_cfg() -> WalkForwardConfig:
    return WalkForwardConfig(train_bars=120, test_bars=40, step_bars=40, folds=2, target_column="forward_return_bps", embargo_bars=0)


def test_benchmark_variants_diverge_when_cross_exchange_path_changes(monkeypatch):
    settings = Settings(_env_file=None)
    session = ResearchSession.from_candles(
        settings,
        "BTCUSDT",
        Timeframe.H1,
        make_candles(n=260, drift=1.0, vol=0.001),
        snapshots={
            "funding": FundingRate(symbol="BTCUSDT", exchange="test", rate=0.0005),
            "open_interest": OpenInterest(symbol="BTCUSDT", exchange="test", open_interest=120.0),
            "orderbook": OrderBook(
                symbol="BTCUSDT",
                exchange="test",
                bids=[OrderBookLevel(price=100.0, size=3.0)],
                asks=[OrderBookLevel(price=101.0, size=1.0)],
            ),
        },
    )
    runner = BenchmarkRunner(settings)

    def fake_compute_signal(candles, timeframe, factor_overrides, regime, regime_conf, cfg=None, **kwargs):  # noqa: ARG001
        del kwargs, cfg, regime, regime_conf
        side = Side.LONG if factor_overrides else Side.SHORT
        sig = make_signal(confidence=0.45, timeframe=timeframe, side=side)
        sig.raw_confidence = 0.45
        sig.entry_state = SignalEntryState.ENTER_NOW
        sig.max_wait_bars = 0
        return sig

    monkeypatch.setattr("twa.research.benchmarking.compute_signal", fake_compute_signal)

    technical = runner._production_engine(
        session,
        _wf_cfg(),
        variant=ProductionVariant(name=PRODUCTION_ENGINE_TECHNICAL_ONLY, technical_only=True, news_dampen=1.0),
    )
    full = runner._production_engine(
        session,
        _wf_cfg(),
        variant=ProductionVariant(name=PRODUCTION_ENGINE_NO_NEWS_GUARD, technical_only=False, news_dampen=1.0),
    )

    assert technical.name == PRODUCTION_ENGINE_TECHNICAL_ONLY
    assert full.name == PRODUCTION_ENGINE_NO_NEWS_GUARD
    assert (technical.trades, technical.edge_per_trade_bps, technical.hit_rate) != (
        full.trades,
        full.edge_per_trade_bps,
        full.hit_rate,
    )


def test_benchmark_variants_diverge_when_news_guard_changes_acceptance(monkeypatch):
    settings = Settings(_env_file=None)
    session = ResearchSession.from_candles(settings, "BTCUSDT", Timeframe.H1, make_candles(n=260, drift=1.0, vol=0.001))
    runner = BenchmarkRunner(settings)

    def fake_compute_signal(candles, timeframe, factor_overrides, regime, regime_conf, cfg=None, **kwargs):  # noqa: ARG001
        del candles, factor_overrides, regime, regime_conf, cfg, kwargs
        sig = make_signal(confidence=0.21, timeframe=timeframe)
        sig.raw_confidence = 0.21
        sig.entry_state = SignalEntryState.ENTER_NOW
        sig.max_wait_bars = 0
        return sig

    monkeypatch.setattr("twa.research.benchmarking.compute_signal", fake_compute_signal)

    guarded = runner._production_engine(
        session,
        _wf_cfg(),
        variant=ProductionVariant(name=PRODUCTION_ENGINE_WITH_NEWS_GUARD, technical_only=False, news_dampen=0.85),
    )
    unguarded = runner._production_engine(
        session,
        _wf_cfg(),
        variant=ProductionVariant(name=PRODUCTION_ENGINE_NO_NEWS_GUARD, technical_only=False, news_dampen=1.0),
    )

    assert guarded.trades == 0
    assert unguarded.trades > 0


@pytest.mark.asyncio
async def test_lifecycle_moves_breakeven_to_midpoint_and_releases_risk_slot(tmp_path):
    settings = Settings(_env_file=None, signal_outcomes_db_path=tmp_path / "signals.sqlite3")
    risk = RiskEngine(settings)
    store = SignalOutcomeStore(settings)
    lifecycle = SignalLifecycleManager(store, SilentTelegram(), risk_engine=risk)
    await lifecycle.start()
    try:
        sig = make_signal(confidence=0.6)
        risk.active_ids.append(sig.id)
        lifecycle.active[sig.id] = LiveSignalState(signal=sig, state=SignalLifecycleState.ACTIVE, published=True, effective_invalidation=sig.invalidation)
        await lifecycle.update_price(sig.symbol, 102.0, sig.regime)
        assert lifecycle.active[sig.id].effective_invalidation == pytest.approx(100.25, abs=1e-6)
        await lifecycle.update_price(sig.symbol, 100.2, sig.regime)
        assert sig.id not in lifecycle.active
        assert sig.id not in risk.active_ids
    finally:
        await lifecycle.stop()


@pytest.mark.asyncio
async def test_lifecycle_restores_waiting_candidates_from_store(tmp_path):
    settings = Settings(_env_file=None, signal_outcomes_db_path=tmp_path / "signals.sqlite3")
    sig = make_signal(confidence=0.6)
    sig.entry_state = SignalEntryState.WAIT
    sig.max_wait_bars = 2

    store = SignalOutcomeStore(settings)
    await store.start()
    try:
        await store.upsert_signal(sig, state="DETECTED")
    finally:
        await store.stop()

    restored_store = SignalOutcomeStore(settings)
    lifecycle = SignalLifecycleManager(restored_store, SilentTelegram(), risk_engine=RiskEngine(settings))
    await lifecycle.start()
    try:
        assert sig.id in lifecycle.candidates
    finally:
        await lifecycle.stop()
