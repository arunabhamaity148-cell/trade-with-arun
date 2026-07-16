"""Rolling walk-forward validation harness."""
from __future__ import annotations

from typing import Callable, List

import pandas as pd
from pydantic import BaseModel, Field

from twa.research.utils import sharpe_like


class WalkForwardConfig(BaseModel):
    train_bars: int = 120
    test_bars: int = 40
    step_bars: int = 40
    folds: int = 5
    target_column: str = "forward_return"


class WalkForwardFold(BaseModel):
    fold: int
    train_start: int
    train_end: int
    test_start: int
    test_end: int
    trades: int
    mean_return: float
    sharpe_like: float


class WalkForwardResult(BaseModel):
    folds: List[WalkForwardFold] = Field(default_factory=list)
    mean_out_sample: float = 0.0
    variance_out_sample: float = 0.0
    stability: float = 0.0
    trade_count: int = 0


class WalkForwardValidator:
    """Generic walk-forward runner for model or parameter validation."""

    def run(
        self,
        frame: pd.DataFrame,
        fit_predict: Callable[[pd.DataFrame, pd.DataFrame], pd.Series],
        config: WalkForwardConfig,
    ) -> WalkForwardResult:
        folds: List[WalkForwardFold] = []
        metrics: List[float] = []
        trades = 0
        for fold in range(config.folds):
            train_start = fold * config.step_bars
            train_end = train_start + config.train_bars
            test_start = train_end
            test_end = test_start + config.test_bars
            if test_end > len(frame):
                break
            train = frame.iloc[train_start:train_end].reset_index(drop=True)
            test = frame.iloc[test_start:test_end].reset_index(drop=True)
            positions = fit_predict(train, test).reindex(test.index).fillna(0.0)
            returns = (positions * test[config.target_column])[positions != 0]
            metric = float(returns.mean()) if len(returns) else 0.0
            metrics.append(metric)
            trades += int((positions != 0).sum())
            folds.append(WalkForwardFold(
                fold=fold,
                train_start=train_start,
                train_end=train_end,
                test_start=test_start,
                test_end=test_end,
                trades=int((positions != 0).sum()),
                mean_return=metric,
                sharpe_like=sharpe_like(returns),
            ))
        variance = float(pd.Series(metrics, dtype=float).var(ddof=1)) if len(metrics) > 1 else 0.0
        stability = float(1.0 / (1.0 + variance))
        return WalkForwardResult(
            folds=folds,
            mean_out_sample=float(pd.Series(metrics, dtype=float).mean()) if metrics else 0.0,
            variance_out_sample=variance,
            stability=stability,
            trade_count=trades,
        )
