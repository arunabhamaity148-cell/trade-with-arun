from __future__ import annotations

import pandas as pd

from twa.config import Settings
from twa.models.types import Side, Timeframe
from twa.research.benchmarking import BenchmarkConfig, BenchmarkRunner, PRODUCTION_ENGINE_NO_NEWS_GUARD, PRODUCTION_ENGINE_WITH_NEWS_GUARD
from twa.research.calibration_pipeline import CalibrationPipeline
from twa.research.edge_validation import benjamini_hochberg
from twa.research.labels import SignalGeometry, label_signal_outcome
from twa.research.lab import ResearchSession
from twa.research.point_in_time import assert_future_data_does_not_move_past_features, feature_store_manifest
from twa.research.walk_forward import WalkForwardConfig, WalkForwardValidator
from tests.conftest import make_candles


def test_point_in_time_feature_manifest_and_leakage_guard(tmp_path):
    candles = make_candles(n=180, drift=1.2, vol=0.01)
    manifest = feature_store_manifest()
    assert "feature" in manifest.columns
    stable = assert_future_data_does_not_move_past_features(
        "BTCUSDT",
        Timeframe.H1,
        candles,
        cutoff_index=120,
        mutate=lambda future: [bar.model_copy(update={"close": bar.close * 10.0, "high": bar.high * 10.0, "low": bar.low * 10.0}) for bar in future],
    )
    assert stable


def test_label_signal_outcome_is_as_of_future_only():
    candles = make_candles(n=120, drift=0.0, vol=0.001)
    geometry = SignalGeometry(
        entry_time=candles[80].open_time,
        entry_price=candles[80].close,
        side=Side.LONG,
        invalidation=candles[80].close * 0.99,
        targets=[candles[80].close * 1.001, candles[80].close * 1.002, candles[80].close * 1.003],
        max_horizon_bars=8,
    )
    label = label_signal_outcome(geometry, candles[80:88])
    assert label.resolution_bars >= 1
    assert label.label in {"target_1", "target_2", "target_3", "stop", "stop_first", "horizon"}


def test_purged_walk_forward_removes_overlapping_rows():
    frame = pd.DataFrame(
        {
            "feature": list(range(40)),
            "forward_return": [0.01] * 40,
            "regime": ["trend_up"] * 40,
            "label_end_index": [i + 5 for i in range(40)],
        }
    )
    seen = {}

    def fit_predict(train: pd.DataFrame, test: pd.DataFrame):
        seen["train_max_label_end"] = int(train["label_end_index"].max())
        return pd.Series(1.0, index=test.index)

    cfg = WalkForwardConfig(train_bars=20, test_bars=5, step_bars=5, folds=1, target_column="forward_return", embargo_bars=3)
    result = WalkForwardValidator().run(frame, fit_predict, cfg)
    assert result.folds[0].purged_rows > 0
    assert seen["train_max_label_end"] < result.folds[0].test_start


def test_benjamini_hochberg_controls_multiple_testing():
    adjusted = benjamini_hochberg([0.01, 0.02, 0.20, 0.50])
    assert adjusted[0] <= adjusted[-1]
    assert max(adjusted) <= 1.0


def test_calibration_pipeline_accepts_out_of_fold_predictions(tmp_path):
    settings = Settings(data_dir=tmp_path, ml_enabled=True, ml_model_path=tmp_path / "models" / "calibrator.joblib")
    frame = pd.DataFrame(
        {
            "prediction": [0.1, 0.2, 0.3, 0.8, 0.9, 0.7] * 20,
            "target": [-5, -1, -2, 3, 6, 2] * 20,
        }
    )
    report = CalibrationPipeline(settings).fit_out_of_fold(frame)
    assert report.rows_used == 120
    assert report.metrics.brier_score >= 0.0
    assert report.drift_summary


def test_benchmark_report_includes_fold_and_regime_breakdowns(tmp_path):
    settings = Settings(data_dir=tmp_path)
    runner = BenchmarkRunner(settings)
    try:
        report = __import__("asyncio").run(runner.run(symbol="BTCUSDT", timeframe=Timeframe.H1, candles=make_candles(n=320, drift=0.8, vol=0.004), config=BenchmarkConfig(walk_forward_folds=3, walk_forward_train_bars=80, walk_forward_test_bars=20, walk_forward_step_bars=20, walk_forward_embargo_bars=4), days=30))
    finally:
        __import__("asyncio").run(runner.close())
    names = {row.name for row in report.strategies}
    assert PRODUCTION_ENGINE_WITH_NEWS_GUARD in names
    assert PRODUCTION_ENGINE_NO_NEWS_GUARD in names
    production_row = next(row for row in report.strategies if row.name == PRODUCTION_ENGINE_NO_NEWS_GUARD)
    assert production_row.fold_breakdown
    assert isinstance(production_row.regime_breakdown, list)
