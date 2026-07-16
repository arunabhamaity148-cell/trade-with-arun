"""Backtest harness — historical replay, walk-forward, MFE/MAE, expectancy.

Honesty contract
----------------
* Zero performance is fabricated.  All numerics come from the data feed.
* If a walk-forward produces insufficient trades (< 30), we report
  `INSUFFICIENT_TRADES` and explicitly decline to print a win rate.
* Any backtest must declare the time window; statistics are local to it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import numpy as np

from twa.config import Settings
from twa.features.engineering import compute_all
from twa.logging import get_logger
from twa.models.types import Candle, RegimeLabel, Side, Timeframe, coerce_timeframe
from twa.regime.classifier import classify, regime_confidence
from twa.risk.engine import RiskEngine
from twa.risk.quality import trade_quality_score
from twa.signal.engine import DEFAULT_CFG, EngineConfig, compute_signal

log = get_logger("backtest")

INTRABAR_CONFLICT_RESOLUTION = "stop_first"


@dataclass
class TradeRecord:
    symbol: str
    timeframe: str
    side: Side
    entry_time: datetime
    entry_price: float
    invalidation: float
    targets: List[float]
    confidence: float
    regime: RegimeLabel
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    exit_reason: str = "open"
    pnl_bps: float = 0.0
    mfe_bps: float = 0.0
    mae_bps: float = 0.0
    holding_bars: int = 0


@dataclass
class BacktestResult:
    window_start: datetime
    window_end: datetime
    trades: List[TradeRecord] = field(default_factory=list)
    note: str = "ok"

    @property
    def total_trades(self) -> int:
        return len(self.trades)

    @property
    def expectancy_bps(self) -> float:
        closed = [t for t in self.trades if t.exit_price is not None]
        if not closed:
            return 0.0
        return float(np.mean([t.pnl_bps for t in closed]))

    def win_rate(self) -> Optional[float]:
        closed = [t for t in self.trades if t.exit_price is not None]
        if len(closed) < 30:
            return None
        return float(sum(1 for t in closed if t.pnl_bps > 0) / len(closed))

    def quality(self) -> Dict[str, float]:
        closed = [t for t in self.trades if t.exit_price is not None]
        if not closed:
            return {"trade_quality_mean": 0.0}
        scores = [
            trade_quality_score(t.pnl_bps, t.mfe_bps, t.mae_bps, t.holding_bars)
            for t in closed
        ]
        return {
            "trade_quality_mean": float(np.mean(scores)),
            "trade_quality_median": float(np.median(scores)),
        }

    def summary(self) -> Dict:
        return {
            "window": [self.window_start.isoformat(), self.window_end.isoformat()],
            "trades": self.total_trades,
            "expectancy_bps": round(self.expectancy_bps, 3),
            "win_rate": self.win_rate(),
            "quality": self.quality(),
            "note": self.note,
        }


def _walk_forward(
    candles: List[Candle],
    timeframe: str,
    train_bars: int = 200,
    test_bars: int = 50,
) -> List[Candle]:
    """Return candles sliced for one walk-forward window (train, test)."""
    del timeframe
    if len(candles) <= train_bars + test_bars:
        return candles
    return candles[-(train_bars + test_bars):]


def simulate(
    candles: List[Candle],
    timeframe: Timeframe | str,
    factor_overrides_list: List[Dict[str, float]],
    high_volatility_threshold: float = 0.85,
    cfg: EngineConfig = DEFAULT_CFG,
    *,
    settings: Optional[Settings] = None,
    news_dampen: float = 1.0,
    ml_calibration: float = 1.0,
    max_active_signals: int = 5,
) -> BacktestResult:
    """Simulate the engine on a candle series.

    Unlike the earlier replay harness, this simulation now applies the same
    risk gating used by the live orchestrator: stressed-regime confidence cap,
    high-volatility dampener, minimum calibrated confidence, per symbol+side
    cooldown, and max-active-signal state.
    """
    if len(candles) < 30:
        now = datetime.now(tz=timezone.utc)
        return BacktestResult(
            candles[0].open_time if candles else now,
            candles[-1].open_time if candles else now,
            note="INSUFFICIENT_DATA",
        )

    tf = coerce_timeframe(timeframe)
    result = BacktestResult(candles[0].open_time, candles[-1].open_time)
    run_settings = settings or Settings(_env_file=None)
    risk = RiskEngine(run_settings)
    active_until: List[Tuple[datetime, str]] = []

    for i in range(60, len(candles) - 16):
        current_bar = candles[i]
        _expire_closed_signals(risk, active_until, current_bar.open_time)

        window = candles[:i]
        features = compute_all(window)
        regime = classify(features)
        reg_conf = regime_confidence(features, regime)
        overrides = factor_overrides_list[i] if i < len(factor_overrides_list) else {}
        sig = compute_signal(
            window,
            tf,
            overrides,
            regime,
            reg_conf,
            cfg=cfg,
            news_dampen=news_dampen,
            ml_calibration=ml_calibration,
        )
        if sig is None:
            continue

        verdict = risk.evaluate(
            sig,
            news_dampen=news_dampen,
            ml_calibration=ml_calibration,
            high_volatility=features.get("realised_vol_30", 0.0) >= high_volatility_threshold,
            stressed_regime=regime == RegimeLabel.STRESSED,
            max_active=max_active_signals,
            current_ts=current_bar.open_time.timestamp(),
        )
        if not verdict.accepted:
            continue

        sig.confidence = float(verdict.adjusted_confidence)
        trade = _realise(sig, candles[i:i + 16])
        result.trades.append(trade)
        if trade.exit_time is not None:
            active_until.append((trade.exit_time, sig.id))

    if result.total_trades < 30:
        result.note = "INSUFFICIENT_TRADES"
    return result


def _expire_closed_signals(
    risk: RiskEngine,
    active_until: List[Tuple[datetime, str]],
    current_time: datetime,
) -> None:
    remaining: List[Tuple[datetime, str]] = []
    for exit_time, sig_id in active_until:
        if exit_time <= current_time:
            risk.invalidate(sig_id, reason="backtest_exit")
            continue
        remaining.append((exit_time, sig_id))
    active_until[:] = remaining


def _realise(sig, future: List[Candle]) -> TradeRecord:
    """Walk forward through `future` bars; decide when and how to exit."""
    entry_price = sig.entry_zone[0]
    if not future:
        return TradeRecord(
            symbol=sig.symbol,
            timeframe=sig.timeframe.value,
            side=sig.side,
            entry_time=datetime.now(tz=timezone.utc),
            entry_price=entry_price,
            invalidation=sig.invalidation,
            targets=list(sig.targets),
            confidence=sig.confidence,
            regime=sig.regime,
            exit_reason="no_data",
        )

    direction = 1 if sig.side == Side.LONG else (-1 if sig.side == Side.SHORT else 0)
    mfe = 0.0
    mae = 0.0
    exit_i = len(future) - 1
    exit_price = future[-1].close
    exit_reason = "horizon"

    for j, bar in enumerate(future):
        move = (bar.close - entry_price) * direction
        move_bps = move / max(entry_price, 1e-9) * 10_000
        mfe = max(mfe, move_bps)
        mae = min(mae, move_bps)

        stop_hit = (direction == 1 and bar.low <= sig.invalidation) or (
            direction == -1 and bar.high >= sig.invalidation
        )
        target_hit = _first_target_hit(sig.targets, bar, direction)

        # With OHLC only, true intrabar sequencing is unknowable. We therefore
        # expose the conservative policy explicitly: if the same candle touches
        # both the stop and a target, the stop is assumed to have been reached
        # first (`stop_first`) rather than relying on control-flow ordering.
        if stop_hit and target_hit is not None:
            if INTRABAR_CONFLICT_RESOLUTION == "stop_first":
                exit_i, exit_price, exit_reason = j, sig.invalidation, "invalidation"
            else:
                tp_idx, tp = target_hit
                exit_i, exit_price, exit_reason = j, tp, f"target_{tp_idx}R"
            break
        if stop_hit:
            exit_i, exit_price, exit_reason = j, sig.invalidation, "invalidation"
            break
        if target_hit is not None:
            tp_idx, tp = target_hit
            exit_i, exit_price, exit_reason = j, tp, f"target_{tp_idx}R"
            break

    pnl_bps = (exit_price - entry_price) * direction / max(entry_price, 1e-9) * 10_000
    return TradeRecord(
        symbol=sig.symbol,
        timeframe=sig.timeframe.value,
        side=sig.side,
        entry_time=future[0].open_time,
        entry_price=entry_price,
        invalidation=sig.invalidation,
        targets=list(sig.targets),
        confidence=sig.confidence,
        regime=sig.regime,
        exit_time=future[exit_i].open_time if future else None,
        exit_price=exit_price,
        exit_reason=exit_reason,
        pnl_bps=float(pnl_bps),
        mfe_bps=float(mfe),
        mae_bps=float(mae),
        holding_bars=int(exit_i + 1),
    )


def _first_target_hit(targets: List[float], bar: Candle, direction: int) -> Optional[Tuple[int, float]]:
    for tp_idx, tp in enumerate(targets, start=1):
        if direction == 1 and bar.high >= tp:
            return tp_idx, tp
        if direction == -1 and bar.low <= tp:
            return tp_idx, tp
    return None


def monte_carlo(trades: List[TradeRecord], runs: int = 1000, seed: int = 42) -> Dict:
    """Shuffle trades to estimate distribution of expectancy."""
    closed = [t for t in trades if t.exit_price is not None]
    if len(closed) < 30:
        return {"note": "INSUFFICIENT_TRADES", "trades_used": len(closed)}
    rng = np.random.default_rng(seed)
    pnls = np.array([t.pnl_bps for t in closed], dtype=float)
    samples = np.empty(runs, dtype=float)
    for k in range(runs):
        idx = rng.integers(0, len(pnls), size=len(pnls))
        samples[k] = pnls[idx].mean()
    return {
        "expectancy_mean_bps": float(samples.mean()),
        "expectancy_std_bps": float(samples.std(ddof=1)),
        "p05_bps": float(np.percentile(samples, 5)),
        "p95_bps": float(np.percentile(samples, 95)),
        "trades_used": len(closed),
        "runs": int(runs),
    }
