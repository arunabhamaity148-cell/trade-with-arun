"""Backtest harness — historical replay, walk-forward, MFE/MAE, expectancy.

Honesty contract
----------------
* Zero performance is fabricated.  All numerics come from the data feed.
* If a walk-forward produces insufficient trades (< 30), we report
  `INSUFFICIENT_TRADES` and explicitly decline to print a win rate.
* Any backtest must declare the time window; statistics are local to it.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np

from twa.logging import get_logger
from twa.models.types import Candle, RegimeLabel, Side
from twa.features.engineering import compute_all
from twa.regime.classifier import classify, regime_confidence
from twa.signal.engine import DEFAULT_CFG, EngineConfig, build_factor_vector, compute_signal
from twa.risk.quality import trade_quality_score

log = get_logger("backtest")


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
            "win_rate": self.win_rate(),  # may be None
            "quality": self.quality(),
            "note": self.note,
        }


def _walk_forward(candles: List[Candle], timeframe: str,
                  train_bars: int = 200, test_bars: int = 50) -> List[Candle]:
    """Return candles sliced for one walk-forward window (train, test)."""
    # Caller uses both halves; this helper just slices.
    if len(candles) <= train_bars + test_bars:
        return candles
    return candles[-(train_bars + test_bars):]


def simulate(
    candles: List[Candle],
    timeframe_str: str,
    factor_overrides_list: List[Dict[str, float]],
    high_volatility_threshold: float = 0.85,
    cfg: EngineConfig = DEFAULT_CFG,
) -> BacktestResult:
    """Simulate the engine on a candle series.

    `factor_overrides_list` is a list of the same length as candles
    indexed (one dict per bar); it lets the caller inject
    funding/OI/obi that are known for that time.  In practice the test
    suite passes zero vectors.
    """
    if len(candles) < 30:
        return BacktestResult(candles[0].open_time if candles else datetime.utcnow(),
                              candles[-1].open_time if candles else datetime.utcnow(),
                              note="INSUFFICIENT_DATA")

    from twa.models.types import Timeframe as TF
    timeframe = TF(timeframe_str)
    result = BacktestResult(candles[0].open_time, candles[-1].open_time)

    for i in range(60, len(candles) - 16):
        window = candles[:i]
        features = compute_all(window)
        regime = classify(features)
        reg_conf = regime_confidence(features, regime)
        overrides = factor_overrides_list[i] if i < len(factor_overrides_list) else {}
        sig = compute_signal(window, timeframe, overrides, regime, reg_conf,
                               cfg=cfg, news_dampen=1.0, ml_calibration=1.0)
        if sig is None:
            continue
        # realise trade outcome using the next 16 bars.
        trade = _realise(sig, candles[i:i + 16], i)
        result.trades.append(trade)

    if result.total_trades < 30:
        result.note = "INSUFFICIENT_TRADES"
    return result


def _realise(sig, future: List[Candle], start_idx: int) -> TradeRecord:
    """Walk forward through `future` bars; decide when and how to exit."""
    last_price = sig.entry_zone[0]
    entry_price = last_price
    if not future:
        return TradeRecord(
            symbol=sig.symbol, timeframe=sig.timeframe.value, side=sig.side,
            entry_time=datetime.now(), entry_price=entry_price,
            invalidation=sig.invalidation, targets=list(sig.targets),
            confidence=sig.confidence, regime=sig.regime, exit_reason="no_data",
        )
    direction = 1 if sig.side == Side.LONG else (-1 if sig.side == Side.SHORT else 0)
    invalid_hit = False
    target_hit = False
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
        # check invalidation (intra-bar high/low)
        if direction == 1 and bar.low <= sig.invalidation:
            exit_i, exit_price, exit_reason = j, sig.invalidation, "invalidation"
            invalid_hit = True
            break
        if direction == -1 and bar.high >= sig.invalidation:
            exit_i, exit_price, exit_reason = j, sig.invalidation, "invalidation"
            invalid_hit = True
            break
        # check targets
        for tp in sig.targets:
            if direction == 1 and bar.high >= tp:
                exit_i, exit_price, exit_reason = j, tp, "target_1R"
                target_hit = True
                break
            if direction == -1 and bar.low <= tp:
                exit_i, exit_price, exit_reason = j, tp, "target_1R"
                target_hit = True
                break
        if target_hit:
            break
    pnl_bps = (exit_price - entry_price) * direction / max(entry_price, 1e-9) * 10_000
    return TradeRecord(
        symbol=sig.symbol, timeframe=sig.timeframe.value, side=sig.side,
        entry_time=bar.open_time if future else sig.created_at,  # last seen
        entry_price=entry_price, invalidation=sig.invalidation, targets=list(sig.targets),
        confidence=sig.confidence, regime=sig.regime,
        exit_time=future[exit_i].open_time if future else None,
        exit_price=exit_price, exit_reason=exit_reason,
        pnl_bps=float(pnl_bps),
        mfe_bps=float(mfe),
        mae_bps=float(mae),
        holding_bars=int(exit_i + 1),
    )


def monte_carlo(trades: List[TradeRecord], runs: int = 1000, seed: int = 42) -> Dict:
    """Shuffle trades to estimate distribution of expectancy.

    Returns expected expectancy mean / std / 5th percentile.
    """
    closed = [t for t in trades if t.exit_price is not None]
    if len(closed) < 30:
        return {"note": "INSUFFICIENT_TRADES",
                "trades_used": len(closed)}
    rng = np.random.default_rng(seed)
    pnls = np.array([t.pnl_bps for t in closed], dtype=float)
    samples = np.empty(runs, dtype=float)
    for k in range(runs):
        idx = rng.integers(0, len(pnls), size=len(pnls))
        samples[k] = pnls[idx].mean()
    return {
        "expectancy_mean_bps": float(samples.mean()),
        "expectancy_std_bps":  float(samples.std(ddof=1)),
        "p05_bps":             float(np.percentile(samples, 5)),
        "p95_bps":             float(np.percentile(samples, 95)),
        "trades_used":         len(closed),
        "runs":                int(runs),
    }
