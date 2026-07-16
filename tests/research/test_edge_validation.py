from twa.config import Settings
from twa.models.types import Timeframe
from twa.research.edge_validation import EdgeValidationFramework, ThresholdStrategy
from twa.research.lab import ResearchSession
from tests.conftest import make_candles


def test_edge_validation_runs_on_threshold_strategy(tmp_path):
    settings = Settings(data_dir=tmp_path)
    candles = make_candles(n=320, timeframe=Timeframe.H1, drift=0.8, vol=0.004)
    session = ResearchSession.from_candles(settings, "BTCUSDT", Timeframe.H1, candles)
    strategy = ThresholdStrategy(name="momentum", feature_name="log_return_16", threshold=0.0)
    result = EdgeValidationFramework().validate(session, strategy)
    assert result.strategy_name == "momentum"
    assert result.out_sample_trades >= 0
