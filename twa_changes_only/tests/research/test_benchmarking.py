import asyncio

from twa.config import Settings
from twa.models.types import Timeframe
from twa.research.benchmarking import BenchmarkRunner, PRODUCTION_ENGINE_TECHNICAL_ONLY, ProductionVariant
from twa.research.lab import ResearchSession
from twa.research.walk_forward import WalkForwardConfig
from tests.conftest import make_candles


def test_benchmarking_compares_baselines(tmp_path):
    settings = Settings(data_dir=tmp_path)
    runner = BenchmarkRunner(settings)
    try:
        report = asyncio.run(runner.run(symbol="BTCUSDT", timeframe=Timeframe.H1, candles=make_candles(n=320), days=30))
    finally:
        asyncio.run(runner.close())
    names = {row.name for row in report.strategies}
    assert PRODUCTION_ENGINE_TECHNICAL_ONLY in names
    assert "buy_and_hold" in names


def test_benchmark_uses_row_level_factor_overrides(tmp_path, monkeypatch):
    settings = Settings(_env_file=None, data_dir=tmp_path)
    session = ResearchSession.from_candles(settings, "BTCUSDT", Timeframe.H1, make_candles(n=340, drift=1.0, vol=0.001))
    frame = session.feature_frame.copy()
    frame["funding"] = 0.0
    frame.loc[frame.index[-80]:, "funding"] = 0.75
    frame["basis"] = 0.0
    frame["oi_delta"] = 0.0
    frame["obi"] = 0.0
    session.feature_frame = frame
    runner = BenchmarkRunner(settings)
    seen = []

    def fake_compute_signal(candles, timeframe, factor_overrides, regime, regime_conf, cfg=None, **kwargs):  # noqa: ARG001
        seen.append(float(factor_overrides.get("funding", 0.0)))
        return None

    monkeypatch.setattr("twa.research.benchmarking.compute_signal", fake_compute_signal)
    runner._production_engine(
        session,
        WalkForwardConfig(train_bars=120, test_bars=40, step_bars=40, folds=2, target_column="forward_return_bps", embargo_bars=4),
        variant=ProductionVariant(name="row_level", technical_only=False, news_dampen=1.0),
    )
    assert seen
    assert max(seen) == 0.75
