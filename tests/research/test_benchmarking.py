import asyncio

from twa.config import Settings
from twa.models.types import Timeframe
from twa.research.benchmarking import BenchmarkRunner
from tests.conftest import make_candles


def test_benchmarking_compares_baselines(tmp_path):
    settings = Settings(data_dir=tmp_path)
    runner = BenchmarkRunner(settings)
    try:
        report = asyncio.run(runner.run(symbol="BTCUSDT", timeframe=Timeframe.H1, candles=make_candles(n=320), days=30))
    finally:
        asyncio.run(runner.close())
    names = {row.name for row in report.strategies}
    assert "production_engine" in names
    assert "buy_and_hold" in names
