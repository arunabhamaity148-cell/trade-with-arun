import pandas as pd

from twa.config import Settings
from twa.ml.calibrator import ConfidenceCalibrator
from twa.research.calibration_pipeline import CalibrationPipeline


def test_calibration_pipeline_trains_and_loads(tmp_path):
    settings = Settings(data_dir=tmp_path, ml_enabled=True, ml_model_path=tmp_path / "models" / "calibrator.joblib")
    frame = pd.DataFrame({
        "confidence": [0.1, 0.2, 0.3, 0.7, 0.8, 0.9] * 20,
        "outcome": [0, 0, 0, 1, 1, 1] * 20,
    })
    report = CalibrationPipeline(settings).fit_frame(frame)
    calibrator = ConfidenceCalibrator(settings)
    calibrator.load()
    calibrated = calibrator.calibrate(0.8)
    assert report.rows_used == 120
    assert 0.0 < calibrated <= 0.99
