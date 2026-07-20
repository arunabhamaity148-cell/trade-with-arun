"""Continuous benchmarking against honest baselines through a purged walk-forward harness."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, List, Optional

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from twa.backtest.replay import _expire_closed_signals, _min_gap_bars, _realise, _resolve_entry
from twa.config import Settings
from twa.features.cross_exchange import normalise_funding, oi_momentum, orderbook_imbalance
from twa.features.engineering import compute_all
from twa.logging import get_logger
from twa.models.types import RegimeLabel, Side, SignalEntryState, Timeframe, coerce_timeframe
from twa.regime.classifier import classify, regime_confidence
from twa.research.lab import ResearchLab, ResearchSession
from twa.research.utils import max_drawdown, sharpe_like
from twa.research.walk_forward import RegimePerformance, WalkForwardConfig, WalkForwardFold, WalkForwardValidator
from twa.risk.engine import RiskEngine
from twa.signal.engine import engine_config_from_settings, project_symbol_factors, compute_signal

log = get_logger("research.benchmarking")

PRODUCTION_ENGINE_TECHNICAL_ONLY = "production_engine_technical_only"
PRODUCTION_ENGINE_WITH_NEWS_GUARD = "production_engine_with_news_guard"
PRODUCTION_ENGINE_NO_NEWS_GUARD = "production_engine_without_news_guard"


@dataclass(frozen=True)
class ProductionVariant:
    name: str
    technical_only: bool
    news_dampen: float
    score_factor_keys: Optional[List[str]] = None


class ProductionGateConfig(BaseModel):
    min_confidence: float = 0.20
    risk_cooldown_s: Optional[int] = None
    max_active_signals: int = 5
    sniper_entry: bool = True
    sniper_max_wait_bars: Optional[int] = None
    fair_value_gap_wait_atr: Optional[float] = None
    fair_value_confirm_band_atr: Optional[float] = None


class PipelineDiagnostics(BaseModel):
    name: str
    candidate_bars: int
    rejection_counts: Dict[str, int] = Field(default_factory=dict)
    fold_breakdown: List[dict] = Field(default_factory=list)
    benchmark: StrategyBenchmark | None = None


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

    def analyze_signal_pipeline(
        self,
        session: ResearchSession,
        wf_cfg: WalkForwardConfig,
        *,
        variant: ProductionVariant,
        gate_config: Optional[ProductionGateConfig] = None,
    ) -> PipelineDiagnostics:
        gate_config = gate_config or ProductionGateConfig()
        benchmark, fold_diagnostics = self._production_engine(session, wf_cfg, variant=variant, gate_config=gate_config, return_diagnostics=True)
        rejection_counts: Dict[str, int] = {}
        candidate_bars = 0
        for row in fold_diagnostics:
            candidate_bars += int(row["candidate_bars"])
            for key, value in row["rejection_counts"].items():
                rejection_counts[key] = rejection_counts.get(key, 0) + int(value)
        return PipelineDiagnostics(
            name=variant.name,
            candidate_bars=candidate_bars,
            rejection_counts=dict(sorted(rejection_counts.items())),
            fold_breakdown=fold_diagnostics,
            benchmark=benchmark,
        )

    def compare_gate_candidates(
        self,
        session: ResearchSession,
        wf_cfg: WalkForwardConfig,
        *,
        variant: ProductionVariant,
        candidates: Dict[str, ProductionGateConfig],
    ) -> Dict[str, PipelineDiagnostics]:
        return {
            name: self.analyze_signal_pipeline(session, wf_cfg, variant=variant, gate_config=gate_cfg)
            for name, gate_cfg in candidates.items()
        }

    def _build_report(self, session: ResearchSession, config: BenchmarkConfig) -> BenchmarkReport:
        df = session.target_frame(1)
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
            self._benchmark_from_walk_forward(
                "ma_crossover",
                df,
                lambda train, test: self._ma_positions(pd.concat([train, test], ignore_index=True), config)
                .iloc[len(train):]
                .reset_index(drop=True),
                wf_cfg,
            ),
            self._random_benchmark(df, config, wf_cfg),
            self._production_engine(
                session,
                wf_cfg,
                variant=ProductionVariant(
                    name=PRODUCTION_ENGINE_TECHNICAL_ONLY,
                    technical_only=True,
                    news_dampen=1.0,
                ),
            ),
            self._production_engine(
                session,
                wf_cfg,
                variant=ProductionVariant(
                    name=PRODUCTION_ENGINE_WITH_NEWS_GUARD,
                    technical_only=False,
                    news_dampen=0.85,
                ),
            ),
            self._production_engine(
                session,
                wf_cfg,
                variant=ProductionVariant(
                    name=PRODUCTION_ENGINE_NO_NEWS_GUARD,
                    technical_only=False,
                    news_dampen=1.0,
                ),
            ),
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

    def _benchmark_from_walk_forward(
        self,
        name: str,
        df: pd.DataFrame,
        fit_predict: Callable[[pd.DataFrame, pd.DataFrame], pd.Series],
        config: WalkForwardConfig,
    ) -> StrategyBenchmark:
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
            rows.append(
                self._benchmark_from_walk_forward(
                    "random_entry",
                    df,
                    lambda train, test, s=seed: self._random_positions(test, seed=s, config=config),
                    wf_cfg,
                )
            )
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

    def _production_engine(
        self,
        session: ResearchSession,
        config: Optional[WalkForwardConfig] = None,
        *,
        variant: ProductionVariant = ProductionVariant(
            name=PRODUCTION_ENGINE_TECHNICAL_ONLY,
            technical_only=True,
            news_dampen=1.0,
        ),
        gate_config: Optional[ProductionGateConfig] = None,
        return_diagnostics: bool = False,
    ) -> StrategyBenchmark | tuple[StrategyBenchmark, List[dict]]:
        df = session.target_frame(1)
        config = config or WalkForwardConfig(target_column="forward_return_bps")
        gate_config = gate_config or ProductionGateConfig()
        folds, fold_diagnostics, all_trades = self._run_production_walk_forward(session, df, config, variant=variant, gate_config=gate_config)
        benchmark = self._strategy_from_trades(variant.name, folds, all_trades)
        if return_diagnostics:
            return benchmark, fold_diagnostics
        return benchmark

    def _run_production_walk_forward(
        self,
        session: ResearchSession,
        df: pd.DataFrame,
        config: WalkForwardConfig,
        *,
        variant: ProductionVariant,
        gate_config: ProductionGateConfig,
    ) -> tuple[List[WalkForwardFold], List[dict], List]:
        candle_idx = {c.open_time: idx for idx, c in enumerate(session.candles)}
        fold_models: List[WalkForwardFold] = []
        fold_diagnostics: List[dict] = []
        all_trades: List = []
        validator = WalkForwardValidator()

        run_settings = self.settings.model_copy(
            update={
                "risk_cooldown_s": self.settings.risk_cooldown_s if gate_config.risk_cooldown_s is None else int(gate_config.risk_cooldown_s),
            }
        )
        engine_cfg = engine_config_from_settings(
            run_settings,
            min_confidence=gate_config.min_confidence,
            fair_value_gap_wait_atr=gate_config.fair_value_gap_wait_atr,
            fair_value_confirm_band_atr=gate_config.fair_value_confirm_band_atr,
            sniper_max_wait_bars=gate_config.sniper_max_wait_bars,
        )
        snapshot_factor_overrides = self._factor_overrides(session, technical_only=variant.technical_only)

        embargo_shift = 0
        for fold in range(config.folds):
            train_start = fold * config.step_bars + embargo_shift
            train_end = train_start + config.train_bars
            test_start = train_end
            test_end = test_start + config.test_bars
            if test_end > len(df):
                break
            train = df.iloc[train_start:train_end].copy().reset_index(drop=False).rename(columns={"index": "_row_index"})
            test = df.iloc[test_start:test_end].copy().reset_index(drop=False).rename(columns={"index": "_row_index"})
            purged = validator._purge_training_overlap(train, test_start, test_end, config)
            del purged  # documented in fold metadata; production path does not fit.

            risk = RiskEngine(run_settings)
            active_until = []
            last_bar_by_key: Dict[str, int] = {}
            trades = []
            rejection_counts: Dict[str, int] = {}
            candidate_bars = 0
            min_gap_bars = _min_gap_bars(run_settings, session.timeframe)

            for _, row in test.iterrows():
                idx = candle_idx.get(row["timestamp"])
                if idx is None or idx < 60:
                    rejection_counts["skipped_insufficient_history"] = rejection_counts.get("skipped_insufficient_history", 0) + 1
                    continue
                candidate_bars += 1
                current_bar = session.candles[idx]
                _expire_closed_signals(risk, active_until, current_bar.open_time)
                window = session.candles[:idx]
                features = compute_all(window)
                regime = classify(features)
                reg_conf = regime_confidence(features, regime)
                factor_overrides = self._factor_overrides_for_row(
                    row,
                    technical_only=variant.technical_only,
                    snapshot_factor_overrides=snapshot_factor_overrides,
                )
                sig = compute_signal(
                    window,
                    session.timeframe,
                    factor_overrides,
                    regime,
                    reg_conf,
                    cfg=engine_cfg,
                    score_factor_keys=variant.score_factor_keys,
                )
                if sig is None:
                    rejection_counts["rejected_signal_below_min_confidence"] = rejection_counts.get("rejected_signal_below_min_confidence", 0) + 1
                    continue
                cd_key = f"{sig.symbol}|{sig.timeframe.value}|{sig.side.value}"
                last_seen = last_bar_by_key.get(cd_key)
                if last_seen is not None and (idx - last_seen) < min_gap_bars:
                    rejection_counts["rejected_backtest_min_gap"] = rejection_counts.get("rejected_backtest_min_gap", 0) + 1
                    continue

                verdict = risk.evaluate(
                    sig,
                    news_dampen=variant.news_dampen,
                    ml_calibration=1.0,
                    high_volatility=features.get("realised_vol_30", 0.0) >= 0.95,
                    stressed_regime=regime == RegimeLabel.STRESSED,
                    max_active=max(1, int(gate_config.max_active_signals)),
                    current_ts=current_bar.open_time.timestamp(),
                )
                if not verdict.accepted:
                    key = f"rejected_risk_{verdict.reason.replace(' ', '_')}"
                    rejection_counts[key] = rejection_counts.get(key, 0) + 1
                    continue

                sig.confidence = float(verdict.adjusted_confidence)
                sig.final_confidence = float(verdict.adjusted_confidence)
                if not gate_config.sniper_entry:
                    sig.entry_state = SignalEntryState.ENTER_NOW
                    sig.entry_trigger = "sniper_disabled"
                    sig.max_wait_bars = 0
                activation = _resolve_entry(sig, session.candles[idx : idx + 16], engine_cfg, sniper_entry=gate_config.sniper_entry)
                if activation is None:
                    rejection_counts["rejected_sniper_wait_timeout"] = rejection_counts.get("rejected_sniper_wait_timeout", 0) + 1
                    risk.invalidate(sig.id, reason="sniper_wait_timeout")
                    continue

                entry_bar_index, entry_price = activation
                trade = _realise(
                    sig,
                    session.candles[idx + entry_bar_index : idx + 16],
                    history_before=session.candles[: idx + entry_bar_index],
                    entry_price=entry_price,
                    settings=run_settings,
                    dynamic_exit_management=True,
                )
                trades.append(trade)
                rejection_counts["realized"] = rejection_counts.get("realized", 0) + 1
                last_bar_by_key[cd_key] = idx
                if trade.exit_time is not None:
                    active_until.append((trade.exit_time, sig.id))
                else:
                    risk.invalidate(sig.id, reason="no_exit_time")

            fold_model = self._fold_from_trades(
                fold=fold,
                train_start=train_start,
                train_end=train_end,
                test_start=test_start,
                test_end=test_end,
                purged_rows=int(len(train) - len(validator._purge_training_overlap(train, test_start, test_end, config))),
                embargo_rows=int(config.embargo_bars),
                trades=trades,
            )
            all_trades.extend(trades)
            fold_models.append(fold_model)
            fold_diagnostics.append(
                {
                    "fold": fold,
                    "candidate_bars": candidate_bars,
                    "rejection_counts": dict(sorted(rejection_counts.items())),
                    "fold_metrics": fold_model.model_dump(),
                }
            )
            embargo_shift += int(config.embargo_bars)
        return fold_models, fold_diagnostics, all_trades

    def _strategy_from_trades(self, name: str, folds: List[WalkForwardFold], trades: List) -> StrategyBenchmark:
        series = pd.Series([float(t.pnl_bps) for t in trades], dtype=float)
        if not series.empty:
            hit_rate = float((series > 0).mean())
            edge = float(series.mean())
            dd = float(abs(max_drawdown(series)))
            sharpe = sharpe_like(series)
        else:
            hit_rate = edge = dd = sharpe = 0.0
        regime_groups: Dict[str, List[float]] = {}
        for trade in trades:
            regime_groups.setdefault(str(trade.regime.value), []).append(float(trade.pnl_bps))
        regime_breakdown = []
        for regime, values in sorted(regime_groups.items()):
            regime_series = pd.Series(values, dtype=float)
            regime_breakdown.append(
                RegimePerformance(
                    regime=regime,
                    trades=int(len(regime_series)),
                    mean_return=float(regime_series.mean()) if not regime_series.empty else 0.0,
                    sharpe_like=sharpe_like(regime_series),
                ).model_dump()
            )
        return StrategyBenchmark(
            name=name,
            trades=int(len(trades)),
            edge_per_trade_bps=edge,
            hit_rate=hit_rate,
            drawdown_bps=dd,
            sharpe_like=sharpe,
            fold_breakdown=[row.model_dump() for row in folds],
            regime_breakdown=regime_breakdown,
        )

    def _fold_from_trades(
        self,
        *,
        fold: int,
        train_start: int,
        train_end: int,
        test_start: int,
        test_end: int,
        purged_rows: int,
        embargo_rows: int,
        trades: List,
    ) -> WalkForwardFold:
        returns = pd.Series([float(t.pnl_bps) for t in trades], dtype=float)
        regime_rows: List[RegimePerformance] = []
        regime_groups: Dict[str, List[float]] = {}
        for trade in trades:
            regime_groups.setdefault(str(trade.regime.value), []).append(float(trade.pnl_bps))
        for regime, values in sorted(regime_groups.items()):
            series = pd.Series(values, dtype=float)
            regime_rows.append(
                RegimePerformance(
                    regime=regime,
                    trades=int(len(series)),
                    mean_return=float(series.mean()) if not series.empty else 0.0,
                    sharpe_like=sharpe_like(series),
                )
            )
        return WalkForwardFold(
            fold=fold,
            train_start=train_start,
            train_end=train_end,
            test_start=test_start,
            test_end=test_end,
            trades=int(len(trades)),
            mean_return=float(returns.mean()) if not returns.empty else 0.0,
            sharpe_like=sharpe_like(returns),
            purged_rows=purged_rows,
            embargo_rows=embargo_rows,
            regime_breakdown=regime_rows,
        )

    def _factor_overrides(self, session: ResearchSession, *, technical_only: bool) -> Dict[str, float]:
        if technical_only:
            return {}
        funding = session.snapshots.get("funding") if isinstance(session.snapshots, dict) else None
        open_interest = session.snapshots.get("open_interest") if isinstance(session.snapshots, dict) else None
        orderbook = session.snapshots.get("orderbook") if isinstance(session.snapshots, dict) else None
        basis = 0.0
        if isinstance(session.snapshots, dict) and session.snapshots.get("basis") is not None:
            basis = float(session.snapshots["basis"])
        return project_symbol_factors(
            funding_norm=normalise_funding(funding),
            basis_norm=basis,
            oi_delta_norm=oi_momentum(getattr(open_interest, "open_interest", None), None),
            obi_norm=orderbook_imbalance(orderbook, depth=10),
        )

    def _factor_overrides_for_row(
        self,
        row,
        *,
        technical_only: bool,
        snapshot_factor_overrides: Dict[str, float],
    ) -> Dict[str, float]:
        if technical_only:
            return {}
        overrides = dict(snapshot_factor_overrides)
        for key in ("funding", "basis", "oi_delta", "obi"):
            value = getattr(row, key, None)
            if value is None:
                continue
            try:
                fvalue = float(value)
            except (TypeError, ValueError):
                continue
            if np.isnan(fvalue):
                continue
            overrides[key] = fvalue
        return overrides
