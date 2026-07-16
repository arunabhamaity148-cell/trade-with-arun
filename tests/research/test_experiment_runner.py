import json
import asyncio

from twa.config import Settings
from twa.research.experiment_runner import ExperimentRunner
from tests.conftest import make_candles


def test_experiment_runner_persists_results(tmp_path):
    settings = Settings(data_dir=tmp_path)
    config_path = tmp_path / "experiment.json"
    config_path.write_text(json.dumps({
        "name": "smoke",
        "symbols": ["BTCUSDT"],
        "timeframe": "1h",
        "lookback_bars": 250,
        "strategy": {"feature_name": "log_return_16", "threshold": 0.0},
    }), encoding="utf-8")
    runner = ExperimentRunner(settings)
    candles_map = {"BTCUSDT": make_candles(n=260)}
    try:
        result = asyncio.run(runner.run_config_path(config_path, candles_map=candles_map))
    finally:
        asyncio.run(runner.close())
    assert result.results
    assert (tmp_path / "research" / "experiments").exists()
