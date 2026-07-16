from twa.config import Settings
from twa.models.types import Timeframe
from twa.research.feature_drift import FeatureDriftDetector
from twa.research.lab import ResearchSession
from tests.conftest import make_candles


def test_feature_drift_flags_shifted_feature(tmp_path):
    settings = Settings(data_dir=tmp_path)
    candles = make_candles(n=260, timeframe=Timeframe.H1)
    session = ResearchSession.from_candles(settings, "BTCUSDT", Timeframe.H1, candles)
    frame = session.target_frame(4)
    frame.loc[frame.index[len(frame)//2:], "log_return_16"] += 5.0
    report = FeatureDriftDetector().detect(frame, feature_names=["log_return_16"])
    assert "log_return_16" in report.drifted_features
