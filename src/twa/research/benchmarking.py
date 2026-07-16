"""Continuous benchmarking against simple baselines."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Optional

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from twa.backtest.replay import simulate
from twa.config import Settings
from twa.logging import get_logger
from twa.models.types import Candle, Timeframe, coerce_timeframe
from twa.research.lab import ResearchLab, ResearchSession
from twa.research.utils import max_drawdown, sharpe_like

log = get_logger("research.benchmarking")

PRODUCTION_ENGINE_TECHNICAL_ONLY = "production_engine_technical_only"


class BenchmarkConfig(BaseModel):
    ma_fast: int = 10
    ma_slow: int = 30
    random_seed: int = 42
    random_trade_prob: float = 0.15


class StrategyBenchmark(BaseModel):
    name: str
    trades: int
    edge_per_trade_bps: float
    hit_rate: float
    drawdown_bps: float
    sharpe_like: float


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
        candles: Optional[List[Candle]] = None,
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
        rows = [
            self._from_positions("buy_and_hold", pd.Series(1.0, index=df.index), df),
            self._from_positions("ma_crossover", self._ma_positions(df, config), df),
            self._from_positions("random_entry", self._random_positions(df, config), df),
            self._production_engine(session),
        ]
        rows.sort(key=lambda r: r.edge_per_trade_bps, reverse=True)
        window = [
            session.started_at.isoformat() if session.started_at else "n/a",
            session.ended_at.isoformat() if session.ended_at else "n/a",
        ]
        return BenchmarkReport(
            symbol=session.symbol,
            timeframe=session.timeframe.value,
            window=window,
            strategies=rows,
            best_strategy=rows[0].name if rows else "",
        )

    def _ma_positions(self, df: pd.DataFrame, config: BenchmarkConfig) -> pd.Series:
        fast = df["close"].rolling(config.ma_fast).mean()
        slow = df["close"].rolling(config.ma_slow).mean()
        return pd.Series(np.where(fast > slow, 1.0, -1.0), index=df.index).fillna(0.0)

    def _random_positions(self, df: pd.DataFrame, config: BenchmarkConfig) -> pd.Series:
        rng = np.random.default_rng(config.random_seed)
        mask = rng.random(len(df)) < config.random_trade_prob
        direction = rng.choice([-1.0, 1.0], size=len(df))
        return pd.Series(np.where(mask, direction, 0.0), index=df.index)

    def _from_positions(self, name: str, positions: pd.Series, df: pd.DataFrame) -> StrategyBenchmark:
        rets = (positions * df["forward_return_bps"])[positions != 0]
        return StrategyBenchmark(
            name=name,
            trades=int((positions != 0).sum()),
            edge_per_trade_bps=float(rets.mean()) if len(rets) else 0.0,
            hit_rate=float((rets > 0).mean()) if len(rets) else 0.0,
            drawdown_bps=float(abs(max_drawdown(rets))) if len(rets) else 0.0,
            sharpe_like=sharpe_like(rets),
        )

    def _production_engine(self, session: ResearchSession) -> StrategyBenchmark:
        """Benchmark the replay engine with technical factors only.

        Historical funding / basis / OI-delta / orderbook-imbalance values are not
        reconstructible from the current free-data research session inputs. The
        benchmark row is therefore labelled explicitly as technical-only so it is
        not mistaken for a like-for-like replay of live cross-exchange behaviour.
        """
        log.warning(
            "research.benchmark.production_engine_limited",
            symbol=session.symbol,
            timeframe=session.timeframe.value,
            limitation="historical cross-exchange factors unavailable; benchmark is technical-only",
        )
        result = simulate(
            session.candles,
            session.timeframe,
            factor_overrides_list=[{}] * len(session.candles),
            settings=session.settings,
        )
        closed = [t.pnl_bps for t in result.trades if t.exit_price is not None]
        series = pd.Series(closed, dtype=float)
        return StrategyBenchmark(
            name=PRODUCTION_ENGINE_TECHNICAL_ONLY,
            trades=result.total_trades,
            edge_per_trade_bps=float(result.expectancy_bps),
            hit_rate=float(result.win_rate() or 0.0),
            drawdown_bps=float(abs(max_drawdown(series))) if len(series) else 0.0,
            sharpe_like=sharpe_like(series),
        )
