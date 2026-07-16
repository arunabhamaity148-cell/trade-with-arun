"""ML calibrator tests."""
from twa.config import Settings
from twa.ml.calibrator import ConfidenceCalibrator, IdentityCalibrator


def test_identity_calibrator_returns_one():
    c = IdentityCalibrator()
    assert c.calibrate(0.1) == 1.0
    assert c.calibrate(0.9) == 1.0


def test_calibrator_with_disabled_returns_one():
    s = Settings(_env_file=None, ml_enabled=False)
    c = ConfidenceCalibrator(s)
    c.load()
    assert c.calibrate(0.5) == 1.0


def test_calibrator_with_missing_model_returns_one(tmp_path):
    s = Settings(_env_file=None, ml_enabled=True,
                 ml_model_path=tmp_path / "missing.joblib")
    c = ConfidenceCalibrator(s)
    c.load()
    assert c.calibrate(0.5) == 1.0
