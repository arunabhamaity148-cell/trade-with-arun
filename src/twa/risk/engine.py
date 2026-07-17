"""Institutional-quality risk framework.

Responsibilities
----------------
* Cooldowns between signals for the same symbol+side to avoid overtrading.
* Confidence calibration against volatility (lower confidence when realised vol spikes).
* Adaptive stops using ATR-based invalidation already in the signal engine.
* Exposure protection at the orchestrator level (max signals active simultaneously).
* Signal *invalidation* — reject stale, low-quality, or noisy signals.

This module is purely *advisory* — it never places orders.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from twa.config import Settings
from twa.logging import get_logger
from twa.models.types import SignalIdea

log = get_logger("risk")


@dataclass
class CooldownBook:
    """In-memory map of (symbol, side) → earliest next-signal epoch."""

    _last: Dict[str, float] = field(default_factory=dict)

    def is_cool(self, key: str, cooldown_s: int, *, now: Optional[float] = None) -> bool:
        ts_now = time.time() if now is None else float(now)
        ts = self._last.get(key)
        if ts is None:
            return True
        return (ts_now - ts) >= cooldown_s

    def mark(self, key: str, *, now: Optional[float] = None) -> None:
        self._last[key] = time.time() if now is None else float(now)


@dataclass(frozen=True)
class RiskVerdict:
    accepted: bool
    reason: str
    adjusted_confidence: float
    news_dampen_applied: float = 1.0
    ml_calibration_applied: float = 1.0


class RiskEngine:
    """Stateless, dependency-injected risk decision engine."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.cooldowns = CooldownBook()
        self.active_ids: List[str] = []

    def evaluate(
        self,
        sig: SignalIdea,
        *,
        news_dampen: float,
        ml_calibration: float,
        high_volatility: bool,
        stressed_regime: bool,
        max_active: int = 5,
        current_ts: Optional[float] = None,
    ) -> RiskVerdict:
        """Return whether to accept (publish) a candidate signal.

        `current_ts` is optional to preserve live behaviour while allowing replay/
        backtest callers to evaluate cooldowns against a simulated timeline.
        """

        cd_key = f"{sig.symbol}|{sig.timeframe}|{sig.side.value}"
        if not self.cooldowns.is_cool(cd_key, self.settings.risk_cooldown_s, now=current_ts):
            return RiskVerdict(False, "cooldown active", sig.confidence)

        if sig.confidence > self.settings.risk_max_confidence:
            sig_adjusted = float(self.settings.risk_max_confidence)
        else:
            sig_adjusted = sig.confidence

        # Stress regime → cap very tightly.
        if stressed_regime:
            sig_adjusted = min(sig_adjusted, 0.35)

        if high_volatility:
            sig_adjusted *= 0.75  # soft dampener

        # News dampen must always be ≤ 1.
        nd = float(min(1.0, max(0.1, news_dampen)))
        calibrated = min(self.settings.risk_max_confidence, sig_adjusted * nd * float(ml_calibration))

        if calibrated < 0.20:
            return RiskVerdict(
                False,
                "calibrated_confidence_below_threshold",
                calibrated,
                nd,
                ml_calibration,
            )

        if len(self.active_ids) >= max_active:
            return RiskVerdict(
                False,
                "max_active_signals_reached",
                calibrated,
                nd,
                ml_calibration,
            )

        # OK → accept & mark
        self.cooldowns.mark(cd_key, now=current_ts)
        self.active_ids.append(sig.id)
        if len(self.active_ids) > max_active:
            self.active_ids = self.active_ids[-max_active:]

        log.info(
            "risk.accept",
            symbol=sig.symbol,
            side=sig.side.value,
            regime=sig.regime.value,
            confidence=round(calibrated, 3),
        )
        return RiskVerdict(True, "ok", calibrated, nd, ml_calibration)

    def invalidate(self, sig_id: str, reason: str) -> None:
        if sig_id in self.active_ids:
            self.active_ids.remove(sig_id)
        log.info("risk.invalidate", sig=sig_id, reason=reason)
