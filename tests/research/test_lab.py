from twa.config import Settings
from twa.models.types import Timeframe
from twa.research.lab import ResearchSession
from tests.conftest import make_candles


def test_research_session_builds_target_frame(tmp_path):
    settings = Settings(data_dir=tmp_path)
    candles = make_candles(n=220, timeframe=Timeframe.H1)
    session = ResearchSession.from_candles(settings, "BTCUSDT", Timeframe.H1, candles)
    target = session.target_frame(4)
    assert not target.empty
    assert "forward_return" in target.columns
