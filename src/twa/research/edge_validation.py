"""In-sample/out-of-sample edge validation with significance and sensitivity checks."""
from __future__ import annotations

from typing import Callable, Dict, Iterable, List

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from twa.logging import get_logger
from twa.research.lab import ResearchSession
from twa.research.utils import sharpe_like
from twa.research.walk_forward import WalkForwardConfig, WalkForwardValidator

log = get_logger("research.edge_validation")


class ThresholdStrategy(BaseModel):
    name: str
    feature_name: str
    threshold: float = 0.0
    direction: str = "above"
    trade_side: str = "long"
    horizon: int = 4
    sensitivity_pct: float = 0.10


class EdgeValidationResult(BaseModel):
    strategy_name: str
    passed: bool
    in_sample_trades: int
    out_sample_trades: int
    in_sample_mean_bps: float
    out_sample_mean_bps: float
    in_sample_sharpe: float
    out_sample_sharpe: float
    p_value: float
    q_value: float = 1.0
    sensitivity: Dict[str, float] = Field(default_factory=dict)
    note: str = "ok"


def benjamini_hochberg(p_values: Iterable[float]) -> List[float]:
    pairs = sorted((float(p), idx) for idx, p in enumerate(p_values))
    n = len(pairs)
    adjusted = [1.0] * n
    running = 1.0
    for rank, (p_value, idx) in enumerate(reversed(pairs), start=1):
        denom = max(1, n - rank + 1)
        running = min(running, p_value * n / denom)
        adjusted[idx] = float(min(1.0, running))
    return adjusted


class EdgeValidationFramework:
    """Validate candidate strategies without mutating production logic."""

    def validate(
        self,
        session: ResearchSession,
        strategy: ThresholdStrategy | Callable[[pd.DataFrame], pd.Series],
        *,
        in_sample_frac: float = 0.7,
        bootstrap_runs: int = 400,
    ) -> EdgeValidationResult:
        if isinstance(strategy, ThresholdStrategy):
            df = session.target_frame(strategy.horizon)
            positions = self._positions_from_threshold(df, strategy)
            name = strategy.name
        else:
            df = session.target_frame(4)
            positions = strategy(df).fillna(0.0)
            name = getattr(strategy, "__name__", "callable_strategy")
        returns = positions * df["forward_return_bps"]
        split = max(1, int(len(df) * in_sample_frac))
        train_rets = returns.iloc[:split][positions.iloc[:split] != 0]
        test_rets = returns.iloc[split:][positions.iloc[split:] != 0]
        in_mean = float(train_rets.mean()) if len(train_rets) else 0.0
        out_mean = float(test_rets.mean()) if len(test_rets) else 0.0
        in_sharpe = sharpe_like(train_rets)
        out_sharpe = sharpe_like(test_rets)
        p_value = self._bootstrap_p_value(test_rets, bootstrap_runs)
        sensitivity = self._sensitivity(session, strategy) if isinstance(strategy, ThresholdStrategy) else {}
        stable = not sensitivity or all(np.sign(v or 0.0) == np.sign(out_mean or 0.0) for v in sensitivity.values())
        q_value = benjamini_hochberg([p_value])[0]
        passed = bool(len(test_rets) >= 10 and out_mean > 0 and in_mean > 0 and q_value <= 0.10 and stable)
        note = "ok" if passed else "FAILED_VALIDATION"
        return EdgeValidationResult(
            strategy_name=name,
            passed=passed,
            in_sample_trades=int(len(train_rets)),
            out_sample_trades=int(len(test_rets)),
            in_sample_mean_bps=in_mean,
            out_sample_mean_bps=out_mean,
            in_sample_sharpe=in_sharpe,
            out_sample_sharpe=out_sharpe,
            p_value=p_value,
            q_value=q_value,
            sensitivity=sensitivity,
            note=note,
        )

    def validate_many(
        self,
        session: ResearchSession,
        strategies: List[ThresholdStrategy],
        *,
        bootstrap_runs: int = 400,
    ) -> List[EdgeValidationResult]:
        results = [self.validate(session, strategy, bootstrap_runs=bootstrap_runs) for strategy in strategies]
        q_values = benjamini_hochberg([row.p_value for row in results])
        updated: List[EdgeValidationResult] = []
        for row, q_value in zip(results, q_values):
            updated.append(row.model_copy(update={"q_value": q_value, "passed": bool(row.out_sample_mean_bps > 0 and q_value <= 0.10 and row.out_sample_trades >= 10)}))
        return updated

    def purged_walk_forward_score(self, session: ResearchSession, strategy: ThresholdStrategy) -> dict:
        frame = session.target_frame(strategy.horizon)
        config = WalkForwardConfig(
            train_bars=max(80, min(160, len(frame) // 2)),
            test_bars=max(20, min(40, len(frame) // 6)),
            step_bars=max(20, min(40, len(frame) // 6)),
            folds=4,
            target_column="forward_return_bps",
            embargo_bars=max(1, int(strategy.horizon)),
        )
        validator = WalkForwardValidator()
        result = validator.run(frame, lambda train, test: self._positions_from_threshold(test.assign(**train.iloc[:0].to_dict()), strategy), config)
        return result.model_dump()

    def _positions_from_threshold(self, df: pd.DataFrame, strategy: ThresholdStrategy) -> pd.Series:
        if strategy.feature_name not in df:
            return pd.Series(0.0, index=df.index)
        signal = df[strategy.feature_name]
        cond = signal >= strategy.threshold if strategy.direction == "above" else signal <= strategy.threshold
        side = 1.0 if strategy.trade_side == "long" else -1.0
        return pd.Series(np.where(cond, side, 0.0), index=df.index, dtype=float)

    def _bootstrap_p_value(self, returns: pd.Series, runs: int) -> float:
        arr = returns.dropna().to_numpy(dtype=float)
        if arr.size < 8:
            return 1.0
        rng = np.random.default_rng(42)
        samples = np.empty(runs, dtype=float)
        for idx in range(runs):
            choice = rng.choice(arr, size=arr.size, replace=True)
            samples[idx] = choice.mean()
        obs = arr.mean()
        if obs >= 0:
            return float(np.mean(samples <= 0.0))
        return float(np.mean(samples >= 0.0))

    def _sensitivity(self, session: ResearchSession, strategy: ThresholdStrategy) -> Dict[str, float]:
        out: Dict[str, float] = {}
        for label, threshold in self._perturbed_thresholds(strategy).items():
            perturbed = strategy.model_copy(update={"threshold": threshold})
            df = session.target_frame(perturbed.horizon)
            positions = self._positions_from_threshold(df, perturbed)
            rets = (positions * df["forward_return_bps"])[positions != 0]
            out[label] = float(rets.mean()) if len(rets) else 0.0
        return out

    def _perturbed_thresholds(self, strategy: ThresholdStrategy) -> Dict[str, float]:
        if abs(strategy.threshold) < 1e-12:
            abs_shift = float(strategy.sensitivity_pct)
            return {
                f"threshold_abs_-{abs_shift:.2f}": -abs_shift,
                f"threshold_abs_+{abs_shift:.2f}": abs_shift,
            }
        return {f"threshold_x{mult:.2f}": strategy.threshold * mult for mult in (1.0 - strategy.sensitivity_pct, 1.0 + strategy.sensitivity_pct)}
