from twa.config import Settings
from twa.models.types import Timeframe
from twa.research.concept_drift import ConceptDriftDetector
from twa.research.lab import ResearchSession
from tests.conftest import make_candles


def test_concept_drift_produces_report(tmp_path):
    settings = Settings(data_dir=tmp_path)
    candles = make_candles(n=260, timeframe=Timeframe.H1, drift=0.2, vol=0.02)
    session = ResearchSession.from_candles(settings, "BTCUSDT", Timeframe.H1, candles)
    report = ConceptDriftDetector().detect(session)
    assert report.rows
    assert report.page_hinkley_stat >= 0.0
