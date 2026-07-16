from twa.config import Settings
from twa.models.types import Timeframe
from twa.research.feature_discovery import FeatureDiscoveryEngine
from twa.research.lab import ResearchSession
from tests.conftest import make_candles


def test_feature_discovery_returns_ranked_rows(tmp_path):
    settings = Settings(data_dir=tmp_path)
    candles = make_candles(n=260, timeframe=Timeframe.H1, drift=0.5)
    session = ResearchSession.from_candles(settings, "BTCUSDT", Timeframe.H1, candles)
    report = FeatureDiscoveryEngine(horizon=4).discover(session)
    assert report.rows
    assert abs(report.rows[0].ic) >= abs(report.rows[-1].ic)
