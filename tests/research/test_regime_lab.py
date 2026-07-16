from twa.config import Settings
from twa.models.types import Timeframe
from twa.research.lab import ResearchSession
from twa.research.regime_lab import RegimeLaboratory
from tests.conftest import make_candles


def test_regime_lab_compares_variants(tmp_path):
    settings = Settings(data_dir=tmp_path)
    candles = make_candles(n=260, timeframe=Timeframe.H1, drift=0.4)
    session = ResearchSession.from_candles(settings, "BTCUSDT", Timeframe.H1, candles)
    report = RegimeLaboratory().compare(session)
    assert report.rows
    assert report.best_variant
