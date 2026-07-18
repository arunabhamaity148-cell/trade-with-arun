"""Purged walk-forward validation harness with embargo and OOF tracking."""
from __future__ import annotations

from typing import Callable, Dict, List, Optional

import pandas as pd
from pydantic import BaseModel, Field

from twa.research.utils import sharpe_like


class WalkForwardConfig(BaseModel):
    train_bars: int = 120
    test_bars: int = 40
    step_bars: int = 40
    folds: int = 5
    target_column: str = "forward_return"
    label_end_column: str = "label_end_index"
    regime_column: str = "regime"
    embargo_bars: int = 0


class RegimePerformance(BaseModel):
    regime: str
    trades: int
    mean_return: float
    sharpe_like: float


class WalkForwardFold(BaseModel):
    fold: int
    train_start: int
    train_end: int
    test_start: int
    test_end: int
    trades: int
    mean_return: float
    sharpe_like: float
    purged_rows: int = 0
    embargo_rows: int = 0
    regime_breakdown: List[RegimePerformance] = Field(default_factory=list)


class WalkForwardResult(BaseModel):
    folds: List[WalkForwardFold] = Field(default_factory=list)
    mean_out_sample: float = 0.0
    variance_out_sample: float = 0.0
    stability: float = 0.0
    trade_count: int = 0
    out_of_fold_predictions: List[dict] = Field(default_factory=list)
    regime_summary: List[RegimePerformance] = Field(default_factory=list)


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
        oof_rows: List[dict] = []
        embargo_shift = 0
        for fold in range(config.folds):
            train_start = fold * config.step_bars + embargo_shift
            train_end = train_start + config.train_bars
            test_start = train_end
            test_end = test_start + config.test_bars
            if test_end > len(frame):
                break
            train = frame.iloc[train_start:train_end].copy().reset_index(drop=False).rename(columns={"index": "_row_index"})
            test = frame.iloc[test_start:test_end].copy().reset_index(drop=False).rename(columns={"index": "_row_index"})
            purged = self._purge_training_overlap(train, test_start, test_end, config)
            positions = fit_predict(purged.drop(columns=["_row_index"]), test.drop(columns=["_row_index"]))
            positions = positions.reindex(test.index).fillna(0.0)
            returns = (positions * test[config.target_column])[positions != 0]
            metric = float(returns.mean()) if len(returns) else 0.0
            metrics.append(metric)
            fold_trades = int((positions != 0).sum())
            trades += fold_trades
            regime_breakdown = self._regime_metrics(test, positions, config)
            folds.append(
                WalkForwardFold(
                    fold=fold,
                    train_start=train_start,
                    train_end=train_end,
                    test_start=test_start,
                    test_end=test_end,
                    trades=fold_trades,
                    mean_return=metric,
                    sharpe_like=sharpe_like(returns),
                    purged_rows=int(len(train) - len(purged)),
                    embargo_rows=int(config.embargo_bars),
                    regime_breakdown=regime_breakdown,
                )
            )
            for idx, (_, row) in enumerate(test.iterrows()):
                oof_rows.append(
                    {
                        "fold": fold,
                        "row_index": int(row["_row_index"]),
                        "timestamp": row.get("timestamp"),
                        "availability_time": row.get("availability_time"),
                        "prediction": float(positions.iloc[idx]),
                        "target": float(row.get(config.target_column, 0.0)),
                        "regime": row.get(config.regime_column),
                    }
                )
            embargo_shift += int(config.embargo_bars)
        variance = float(pd.Series(metrics, dtype=float).var(ddof=1)) if len(metrics) > 1 else 0.0
        stability = float(1.0 / (1.0 + variance))
        return WalkForwardResult(
            folds=folds,
            mean_out_sample=float(pd.Series(metrics, dtype=float).mean()) if metrics else 0.0,
            variance_out_sample=variance,
            stability=stability,
            trade_count=trades,
            out_of_fold_predictions=oof_rows,
            regime_summary=self._aggregate_regime_summary(folds),
        )

    def _purge_training_overlap(
        self,
        train: pd.DataFrame,
        test_start: int,
        test_end: int,
        config: WalkForwardConfig,
    ) -> pd.DataFrame:
        if config.label_end_column not in train:
            return train
        end_idx = train[config.label_end_column].fillna(train["_row_index"]).astype(int)
        overlap = end_idx >= test_start
        return train.loc[~overlap].reset_index(drop=True)

    def _regime_metrics(self, test: pd.DataFrame, positions: pd.Series, config: WalkForwardConfig) -> List[RegimePerformance]:
        if config.regime_column not in test:
            return []
        rows: List[RegimePerformance] = []
        active = test.loc[positions != 0].copy()
        if active.empty:
            return rows
        active["position"] = positions[positions != 0].to_numpy(dtype=float)
        active["ret"] = active["position"] * active[config.target_column]
        for regime, grp in active.groupby(config.regime_column):
            rows.append(
                RegimePerformance(
                    regime=str(regime),
                    trades=int(len(grp)),
                    mean_return=float(grp["ret"].mean()),
                    sharpe_like=sharpe_like(grp["ret"]),
                )
            )
        return rows

    def _aggregate_regime_summary(self, folds: List[WalkForwardFold]) -> List[RegimePerformance]:
        bucket: Dict[str, List[RegimePerformance]] = {}
        for fold in folds:
            for row in fold.regime_breakdown:
                bucket.setdefault(row.regime, []).append(row)
        out: List[RegimePerformance] = []
        for regime, rows in bucket.items():
            total_trades = sum(r.trades for r in rows)
            mean_return = sum(r.mean_return * r.trades for r in rows) / max(total_trades, 1)
            mean_sharpe = sum(r.sharpe_like for r in rows) / max(len(rows), 1)
            out.append(RegimePerformance(regime=regime, trades=total_trades, mean_return=float(mean_return), sharpe_like=float(mean_sharpe)))
        out.sort(key=lambda row: row.regime)
        return out
