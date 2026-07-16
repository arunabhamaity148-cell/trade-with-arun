import pandas as pd

from twa.research.walk_forward import WalkForwardConfig, WalkForwardValidator


def test_walk_forward_runs_multiple_folds():
    frame = pd.DataFrame({
        "feature": list(range(240)),
        "forward_return": [0.001 if i % 2 == 0 else -0.0005 for i in range(240)],
    })

    def fit_predict(train: pd.DataFrame, test: pd.DataFrame):
        threshold = train["feature"].median()
        return (test["feature"] >= threshold).astype(float)

    result = WalkForwardValidator().run(frame, fit_predict, WalkForwardConfig(train_bars=80, test_bars=30, step_bars=20, folds=4))
    assert len(result.folds) >= 3
