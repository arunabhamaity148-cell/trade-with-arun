"""Backtest harness — historical replay, walk-forward, MFE/MAE, expectancy.

Honesty contract
----------------
* Zero performance is fabricated. All numerics come from the data feed.
* If a walk-forward produces insufficient trades (< 30), we report
  `INSUFFICIENT_TRADES` and explicitly decline to print a win rate.
* Costs are explicitly modeled: fees, slippage, and funding carry.
* Intrabar stop/target conflicts use an explicit conservative policy.
"""
from __future__ import annotations

import math
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
    fees_bps: float = 0.0
    slippage_bps: float = 0.0
    funding_bps: float = 0.0
    gross_pnl_bps: float = 0.0


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
        scores = [trade_quality_score(t.pnl_bps, t.mfe_bps, t.mae_bps, t.holding_bars) for t in closed]
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
    return candles[-(train_bars + test_bars) :]


def simulate(
    candles: List[Candle],
    timeframe: Timeframe | str,
    factor_overrides_list: List[Dict[str, float]],
    high_volatility_threshold: float = 0.95,
    cfg: EngineConfig = DEFAULT_CFG,
    *,
    settings: Optional[Settings] = None,
    news_dampen: float = 1.0,
    ml_calibration: float = 1.0,
    max_active_signals: int = 5,
    sniper_entry: bool = True,
    dynamic_exit_management: bool = True,
) -> BacktestResult:
    """Simulate the engine on a candle series with risk gating and costs."""
    if len(candles) < 30:
        now = datetime.now(tz=timezone.utc)
        return BacktestResult(candles[0].open_time if candles else now, candles[-1].open_time if candles else now, note="INSUFFICIENT_DATA")

    tf = coerce_timeframe(timeframe)
    result = BacktestResult(candles[0].open_time, candles[-1].open_time)
    run_settings = settings or Settings(_env_file=None)
    risk = RiskEngine(run_settings)
    active_until: List[Tuple[datetime, str]] = []
    last_bar_by_key: Dict[str, int] = {}
    min_gap_bars = _min_gap_bars(run_settings, tf)

    for i in range(60, len(candles) - 16):
        current_bar = candles[i]
        _expire_closed_signals(risk, active_until, current_bar.open_time)

        window = candles[:i]
        features = compute_all(window)
        regime = classify(features)
        reg_conf = regime_confidence(features, regime)
        overrides = factor_overrides_list[i] if i < len(factor_overrides_list) else {}
        sig = compute_signal(window, tf, overrides, regime, reg_conf, cfg=cfg)
        if sig is None:
            continue

        cd_key = f"{sig.symbol}|{sig.timeframe.value}|{sig.side.value}"
        last_seen = last_bar_by_key.get(cd_key)
        if last_seen is not None and (i - last_seen) < min_gap_bars:
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
        sig.final_confidence = float(verdict.adjusted_confidence)
        last_bar_by_key[cd_key] = i

        activation = _resolve_entry(sig, candles[i : i + 16], cfg, sniper_entry=sniper_entry)
        if activation is None:
            continue
        entry_bar_index, entry_price = activation
        trade = _realise(
            sig,
            candles[i + entry_bar_index : i + 16],
            history_before=candles[: i + entry_bar_index],
            entry_price=entry_price,
            settings=run_settings,
            dynamic_exit_management=dynamic_exit_management,
        )
        result.trades.append(trade)
        if trade.exit_time is not None:
            active_until.append((trade.exit_time, sig.id))

    if result.total_trades < 30:
        result.note = "INSUFFICIENT_TRADES"
    return result


def _min_gap_bars(settings: Settings, timeframe: Timeframe) -> int:
    bar_s = {
        Timeframe.M1: 60,
        Timeframe.M5: 300,
        Timeframe.M15: 900,
        Timeframe.H1: 3600,
        Timeframe.H4: 14_400,
        Timeframe.D1: 86_400,
    }[timeframe]
    seconds_as_bars = int(math.ceil(settings.risk_cooldown_s / bar_s)) if settings.risk_cooldown_s > 0 else 0
    return max(int(settings.backtest_min_bars_between_signals), seconds_as_bars)


def _expire_closed_signals(risk: RiskEngine, active_until: List[Tuple[datetime, str]], current_time: datetime) -> None:
    remaining: List[Tuple[datetime, str]] = []
    for exit_time, sig_id in active_until:
        if exit_time <= current_time:
            risk.invalidate(sig_id, reason="backtest_exit")
            continue
        remaining.append((exit_time, sig_id))
    active_until[:] = remaining


def _resolve_entry(sig, future: List[Candle], cfg: EngineConfig, *, sniper_entry: bool = True) -> Optional[Tuple[int, float]]:
    if not future:
        return None
    immediate_price = float(future[0].open)
    if not sniper_entry or getattr(sig, "entry_state", None) is None or sig.entry_state.value == "enter_now":
        return 0, immediate_price
    fair_value = float(sig.fair_value or immediate_price)
    atr_distance = abs(sig.entry_zone[1] - sig.entry_zone[0]) or max(abs(immediate_price - fair_value), 1e-9)
    band = cfg.fair_value_confirm_band_atr * atr_distance * 2.0
    max_wait = max(1, int(getattr(sig, "max_wait_bars", 1)))
    for j, bar in enumerate(future[:max_wait], start=0):
        if sig.side == Side.LONG:
            if bar.low <= fair_value + band and bar.close >= fair_value:
                return j, float(bar.close)
        else:
            if bar.high >= fair_value - band and bar.close <= fair_value:
                return j, float(bar.close)
    return None


def _realise(
    sig,
    future: List[Candle],
    history_before: Optional[List[Candle]] = None,
    *,
    entry_price: Optional[float] = None,
    settings: Optional[Settings] = None,
    dynamic_exit_management: bool = True,
) -> TradeRecord:
    """Walk forward through `future` bars; decide when and how to exit."""
    settings = settings or Settings(_env_file=None)
    if not future:
        px = float(entry_price if entry_price is not None else sig.entry_zone[0])
        return TradeRecord(
            symbol=sig.symbol,
            timeframe=sig.timeframe.value,
            side=sig.side,
            entry_time=datetime.now(tz=timezone.utc),
            entry_price=px,
            invalidation=sig.invalidation,
            targets=list(sig.targets),
            confidence=sig.confidence,
            regime=sig.regime,
            exit_reason="no_data",
        )

    direction = 1 if sig.side == Side.LONG else -1
    raw_entry = float(entry_price if entry_price is not None else future[0].open)
    entry_exec = _apply_slippage(raw_entry, direction=direction, side="entry", slippage_bps=settings.backtest_slippage_bps)

    mfe = 0.0
    mae = 0.0
    exit_i = len(future) - 1
    exit_price = float(future[-1].close)
    exit_reason = "horizon"

    remaining = 1.0
    realized_gross = 0.0
    realized_fee_bps = settings.backtest_fee_bps
    realized_slippage_bps = settings.backtest_slippage_bps
    hit_targets = 0
    effective_stop = float(sig.invalidation)

    for j, bar in enumerate(future):
        move = (bar.close - entry_exec) * direction
        move_bps = move / max(entry_exec, 1e-9) * 10_000
        mfe = max(mfe, move_bps)
        mae = min(mae, move_bps)

        if dynamic_exit_management and hit_targets == 0 and history_before is not None and j > 0:
            regime_now = classify(compute_all(history_before + future[: j + 1]))
            if (sig.side == Side.LONG and regime_now in {RegimeLabel.TREND_DOWN, RegimeLabel.STRESSED}) or (
                sig.side == Side.SHORT and regime_now in {RegimeLabel.TREND_UP, RegimeLabel.STRESSED}
            ):
                exit_i = j
                exit_price = float(bar.close)
                exit_reason = "regime_flip"
                break

        stop_hit = (direction == 1 and bar.low <= effective_stop) or (direction == -1 and bar.high >= effective_stop)
        target_hit = _first_target_hit(sig.targets, bar, direction, hit_targets + 1)

        if stop_hit and target_hit is not None:
            if INTRABAR_CONFLICT_RESOLUTION == "stop_first":
                exit_i, exit_price, exit_reason = j, effective_stop, "invalidation"
            else:
                tp_idx, tp = target_hit
                exit_i, exit_price, exit_reason = j, tp, f"target_{tp_idx}R"
            break

        if target_hit is not None:
            tp_idx, tp = target_hit
            leg = 1.0 / 3.0 if tp_idx < 3 else remaining
            realized_gross += leg * ((tp - entry_exec) * direction / max(entry_exec, 1e-9) * 10_000)
            realized_fee_bps += leg * settings.backtest_fee_bps
            realized_slippage_bps += leg * settings.backtest_slippage_bps
            remaining = max(0.0, remaining - leg)
            hit_targets = tp_idx
            if dynamic_exit_management and tp_idx == 1:
                effective_stop = entry_exec
            if (not dynamic_exit_management) or remaining <= 1e-9 or tp_idx >= 3:
                exit_i, exit_price, exit_reason = j, tp, f"target_{tp_idx}R"
                break
            continue

        if stop_hit:
            exit_i, exit_price, exit_reason = j, effective_stop, "invalidation" if hit_targets == 0 else "breakeven_stop"
            break

    closing_leg = remaining
    exit_exec = _apply_slippage(float(exit_price), direction=direction, side="exit", slippage_bps=settings.backtest_slippage_bps)
    gross_remaining_bps = closing_leg * ((exit_exec - entry_exec) * direction / max(entry_exec, 1e-9) * 10_000)
    gross_pnl_bps = realized_gross + gross_remaining_bps
    holding_bars = int(exit_i + 1)
    funding_bps = holding_bars * _bar_hours(sig.timeframe) * settings.backtest_funding_bps_per_hour * closing_leg
    total_fees_bps = realized_fee_bps + closing_leg * settings.backtest_fee_bps
    total_slippage_bps = realized_slippage_bps + closing_leg * settings.backtest_slippage_bps
    pnl_bps = gross_pnl_bps - total_fees_bps - total_slippage_bps - funding_bps

    return TradeRecord(
        symbol=sig.symbol,
        timeframe=sig.timeframe.value,
        side=sig.side,
        entry_time=future[0].open_time,
        entry_price=float(entry_exec),
        invalidation=sig.invalidation,
        targets=list(sig.targets),
        confidence=sig.confidence,
        regime=sig.regime,
        exit_time=future[exit_i].open_time if future else None,
        exit_price=float(exit_price),
        exit_reason=exit_reason,
        pnl_bps=float(pnl_bps),
        mfe_bps=float(mfe),
        mae_bps=float(mae),
        holding_bars=holding_bars,
        fees_bps=float(total_fees_bps),
        slippage_bps=float(total_slippage_bps),
        funding_bps=float(funding_bps),
        gross_pnl_bps=float(gross_pnl_bps),
    )


def _first_target_hit(targets: List[float], bar: Candle, direction: int, start_idx: int = 1) -> Optional[Tuple[int, float]]:
    for tp_idx, tp in enumerate(targets[start_idx - 1 :], start=start_idx):
        if direction == 1 and bar.high >= tp:
            return tp_idx, tp
        if direction == -1 and bar.low <= tp:
            return tp_idx, tp
    return None


def _apply_slippage(price: float, *, direction: int, side: str, slippage_bps: float) -> float:
    slip = slippage_bps / 10_000.0
    if side == "entry":
        return price * (1 + slip * direction)
    return price * (1 - slip * direction)


def _bar_hours(timeframe: Timeframe) -> float:
    return {
        Timeframe.M1: 1 / 60.0,
        Timeframe.M5: 5 / 60.0,
        Timeframe.M15: 0.25,
        Timeframe.H1: 1.0,
        Timeframe.H4: 4.0,
        Timeframe.D1: 24.0,
    }[timeframe]


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
