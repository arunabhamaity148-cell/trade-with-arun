"""Continuous benchmarking against honest baselines through a purged walk-forward harness."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable, List, Optional

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from twa.config import Settings
from twa.features.engineering import compute_all
from twa.logging import get_logger
from twa.models.types import Side, Timeframe, coerce_timeframe
from twa.regime.classifier import classify, regime_confidence
from twa.research.lab import ResearchLab, ResearchSession
from twa.research.utils import max_drawdown, sharpe_like
from twa.research.walk_forward import WalkForwardConfig, WalkForwardFold, WalkForwardValidator
from twa.risk.engine import RiskEngine
from twa.signal.engine import compute_signal

log = get_logger("research.benchmarking")

PRODUCTION_ENGINE_TECHNICAL_ONLY = "production_engine_technical_only"
PRODUCTION_ENGINE_WITH_NEWS_GUARD = "production_engine_with_news_guard"
PRODUCTION_ENGINE_NO_NEWS_GUARD = "production_engine_without_news_guard"


class BenchmarkConfig(BaseModel):
    ma_fast: int = 10
    ma_slow: int = 30
    random_seed: int = 42
    random_trade_prob: float = 0.15
    random_seed_runs: int = 20
    walk_forward_train_bars: int = 120
    walk_forward_test_bars: int = 40
    walk_forward_step_bars: int = 40
    walk_forward_folds: int = 5
    walk_forward_embargo_bars: int = 4


class StrategyBenchmark(BaseModel):
    name: str
    trades: int
    edge_per_trade_bps: float
    hit_rate: float
    drawdown_bps: float
    sharpe_like: float
    fold_breakdown: List[dict] = Field(default_factory=list)
    regime_breakdown: List[dict] = Field(default_factory=list)


class BenchmarkReport(BaseModel):
    symbol: str
    timeframe: str
    window: List[str]
    strategies: List[StrategyBenchmark] = Field(default_factory=list)
    best_strategy: str = ""


class BenchmarkRunner:
    """Run production and baseline strategies over the same window."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.lab = ResearchLab(settings)

    async def close(self) -> None:
        await self.lab.close()

    async def run(
        self,
        *,
        symbol: str,
        timeframe: Timeframe | str,
        days: int = 30,
        config: Optional[BenchmarkConfig] = None,
        candles: Optional[List] = None,
    ) -> BenchmarkReport:
        config = config or BenchmarkConfig()
        tf = coerce_timeframe(timeframe)
        if candles is None:
            end = datetime.now(tz=timezone.utc)
            start = end - timedelta(days=days)
            session = await self.lab.load_session(symbol, tf, start=start, end=end)
        else:
            session = ResearchSession.from_candles(self.settings, symbol, tf, candles)
        report = self._build_report(session, config)
        log.info("research.benchmark.complete", symbol=symbol, timeframe=tf.value)
        return report

    def _build_report(self, session: ResearchSession, config: BenchmarkConfig) -> BenchmarkReport:
        df = session.target_frame(1)
        config = config or WalkForwardConfig(target_column="forward_return_bps")
        wf_cfg = WalkForwardConfig(
            train_bars=config.walk_forward_train_bars,
            test_bars=config.walk_forward_test_bars,
            step_bars=config.walk_forward_step_bars,
            folds=config.walk_forward_folds,
            target_column="forward_return_bps",
            embargo_bars=config.walk_forward_embargo_bars,
        )
        rows = [
            self._benchmark_from_walk_forward("buy_and_hold", df, lambda train, test: pd.Series(1.0, index=test.index), wf_cfg),
            self._benchmark_from_walk_forward("ma_crossover", df, lambda train, test: self._ma_positions(pd.concat([train, test], ignore_index=True), config).iloc[len(train):].reset_index(drop=True), wf_cfg),
            self._random_benchmark(df, config, wf_cfg),
            self._production_engine(session, wf_cfg, news_dampen=1.0, name=PRODUCTION_ENGINE_TECHNICAL_ONLY),
            self._production_engine(session, wf_cfg, news_dampen=0.85, name=PRODUCTION_ENGINE_WITH_NEWS_GUARD),
            self._production_engine(session, wf_cfg, news_dampen=1.0, name=PRODUCTION_ENGINE_NO_NEWS_GUARD),
        ]
        rows.sort(key=lambda r: r.edge_per_trade_bps, reverse=True)
        window = [session.started_at.isoformat() if session.started_at else "n/a", session.ended_at.isoformat() if session.ended_at else "n/a"]
        return BenchmarkReport(symbol=session.symbol, timeframe=session.timeframe.value, window=window, strategies=rows, best_strategy=rows[0].name if rows else "")

    def _benchmark_from_walk_forward(self, name: str, df: pd.DataFrame, fit_predict: Callable[[pd.DataFrame, pd.DataFrame], pd.Series], config: WalkForwardConfig) -> StrategyBenchmark:
        result = WalkForwardValidator().run(df, fit_predict, config)
        oof = pd.DataFrame(result.out_of_fold_predictions)
        active = oof[oof["prediction"] != 0].copy() if not oof.empty else pd.DataFrame()
        if not active.empty:
            active["ret"] = active["prediction"] * active["target"]
            series = active["ret"].astype(float)
            hit_rate = float((series > 0).mean())
            edge = float(series.mean())
            dd = float(abs(max_drawdown(series)))
            sharpe = sharpe_like(series)
        else:
            hit_rate = edge = dd = sharpe = 0.0
        return StrategyBenchmark(
            name=name,
            trades=int(len(active)),
            edge_per_trade_bps=edge,
            hit_rate=hit_rate,
            drawdown_bps=dd,
            sharpe_like=sharpe,
            fold_breakdown=[row.model_dump() for row in result.folds],
            regime_breakdown=[row.model_dump() for row in result.regime_summary],
        )

    def _ma_positions(self, df: pd.DataFrame, config: BenchmarkConfig) -> pd.Series:
        fast = df["close"].rolling(config.ma_fast).mean()
        slow = df["close"].rolling(config.ma_slow).mean()
        return pd.Series(np.where(fast > slow, 1.0, -1.0), index=df.index).fillna(0.0)

    def _random_positions(self, df: pd.DataFrame, *, seed: int, config: BenchmarkConfig) -> pd.Series:
        rng = np.random.default_rng(seed)
        mask = rng.random(len(df)) < config.random_trade_prob
        direction = rng.choice([-1.0, 1.0], size=len(df))
        return pd.Series(np.where(mask, direction, 0.0), index=df.index)

    def _random_benchmark(self, df: pd.DataFrame, config: BenchmarkConfig, wf_cfg: WalkForwardConfig) -> StrategyBenchmark:
        rows: List[StrategyBenchmark] = []
        for seed in range(config.random_seed, config.random_seed + max(1, config.random_seed_runs)):
            rows.append(self._benchmark_from_walk_forward("random_entry", df, lambda train, test, s=seed: self._random_positions(test, seed=s, config=config), wf_cfg))
        return StrategyBenchmark(
            name="random_entry",
            trades=int(round(np.mean([r.trades for r in rows]))),
            edge_per_trade_bps=float(np.mean([r.edge_per_trade_bps for r in rows])),
            hit_rate=float(np.mean([r.hit_rate for r in rows])),
            drawdown_bps=float(np.mean([r.drawdown_bps for r in rows])),
            sharpe_like=float(np.mean([r.sharpe_like for r in rows])),
            fold_breakdown=rows[0].fold_breakdown if rows else [],
            regime_breakdown=rows[0].regime_breakdown if rows else [],
        )

    def _production_engine(self, session: ResearchSession, config: Optional[WalkForwardConfig] = None, *, news_dampen: float = 1.0, name: str = PRODUCTION_ENGINE_TECHNICAL_ONLY) -> StrategyBenchmark:
        df = session.target_frame(1)
        config = config or WalkForwardConfig(target_column="forward_return_bps")
        candle_idx = {c.open_time: idx for idx, c in enumerate(session.candles)}
        risk = RiskEngine(self.settings)

        def fit_predict(train: pd.DataFrame, test: pd.DataFrame) -> pd.Series:
            positions: List[float] = []
            for _, row in test.iterrows():
                idx = candle_idx.get(row["timestamp"])
                if idx is None or idx < 30:
                    positions.append(0.0)
                    continue
                window = session.candles[: idx + 1]
                feats = compute_all(window)
                regime = classify(feats)
                reg_conf = regime_confidence(feats, regime)
                sig = compute_signal(window, session.timeframe, {}, regime, reg_conf)
                if sig is None:
                    positions.append(0.0)
                    continue
                verdict = risk.evaluate(
                    sig,
                    news_dampen=news_dampen,
                    ml_calibration=1.0,
                    high_volatility=feats.get("realised_vol_30", 0.0) >= 0.95,
                    stressed_regime=regime == type(regime).STRESSED,
                    current_ts=session.candles[idx].open_time.timestamp(),
                )
                if not verdict.accepted:
                    positions.append(0.0)
                    continue
                positions.append(1.0 if sig.side == Side.LONG else -1.0)
            return pd.Series(positions, index=test.index, dtype=float)

        return self._benchmark_from_walk_forward(name, df, fit_predict, config)
