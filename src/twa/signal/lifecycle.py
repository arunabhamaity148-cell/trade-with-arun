"""Signal lifecycle state machine for post-publication tracking."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

from twa.models.types import RegimeLabel, SignalIdea, SignalLifecycleState, Side
from twa.signal.store import SignalOutcomeStore
from twa.telegram.bot import TelegramBot, render_followup


@dataclass
class LiveSignalState:
    signal: SignalIdea
    state: SignalLifecycleState = SignalLifecycleState.DETECTED
    published: bool = False
    tp_hits: int = 0
    effective_invalidation: float = 0.0
    last_price: Optional[float] = None
    notes: List[str] = field(default_factory=list)


class SignalLifecycleManager:
    def __init__(self, store: SignalOutcomeStore, telegram: TelegramBot):
        self.store = store
        self.telegram = telegram
        self.candidates: Dict[str, LiveSignalState] = {}
        self.active: Dict[str, LiveSignalState] = {}

    async def start(self) -> None:
        await self.store.start()

    async def stop(self) -> None:
        await self.store.stop()

    async def register_candidate(self, sig: SignalIdea) -> None:
        state = LiveSignalState(signal=sig, state=SignalLifecycleState.DETECTED, effective_invalidation=sig.invalidation)
        if sig.entry_state.value == "wait":
            self.candidates[sig.id] = state
        else:
            await self.activate(sig)

    async def activate(self, sig: SignalIdea) -> None:
        state = LiveSignalState(signal=sig, state=SignalLifecycleState.ACTIVE, published=True, effective_invalidation=sig.invalidation)
        self.active[sig.id] = state
        await self.store.upsert_signal(sig, state=SignalLifecycleState.ACTIVE.value)
        await self.telegram.send_signal(sig)

    async def try_activate_candidate(self, sig_id: str, current_price: float) -> bool:
        state = self.candidates.get(sig_id)
        if state is None:
            return False
        sig = state.signal
        fair_value = float(sig.fair_value or current_price)
        if sig.side == Side.LONG and current_price <= fair_value:
            self.candidates.pop(sig_id, None)
            sig.entry_state = sig.entry_state.ENTER_NOW
            await self.activate(sig)
            return True
        if sig.side == Side.SHORT and current_price >= fair_value:
            self.candidates.pop(sig_id, None)
            sig.entry_state = sig.entry_state.ENTER_NOW
            await self.activate(sig)
            return True
        if sig.expires_at and sig.expires_at <= datetime.now(tz=timezone.utc):
            self.candidates.pop(sig_id, None)
            await self.store.upsert_signal(sig, state=SignalLifecycleState.EXPIRED.value, outcome_note="candidate_stale")
        return False

    async def update_price(self, symbol: str, current_price: float, regime: RegimeLabel) -> None:
        for sig_id, state in list(self.active.items()):
            sig = state.signal
            if sig.symbol != symbol:
                continue
            state.last_price = current_price
            if state.tp_hits == 0 and _tp_hit(sig, current_price, 1):
                state.tp_hits = 1
                state.state = SignalLifecycleState.TP1_HIT
                state.effective_invalidation = state.signal.entry_zone[0]
                await self.store.upsert_signal(sig, state=state.state.value, outcome_note="tp1_hit_move_to_breakeven")
                await self.telegram.send_text(render_followup(sig, "TP1 hit — move invalidation to breakeven."))
                continue
            if state.tp_hits < 2 and _tp_hit(sig, current_price, 2):
                state.tp_hits = 2
                state.state = SignalLifecycleState.TP2_HIT
                await self.store.upsert_signal(sig, state=state.state.value, outcome_note="tp2_hit")
                await self.telegram.send_text(render_followup(sig, "TP2 hit — consider trailing the remainder."))
                continue
            if _tp_hit(sig, current_price, 3):
                state.state = SignalLifecycleState.TP3_HIT
                await self.store.upsert_signal(sig, state=state.state.value, outcome_note="tp3_hit_full_resolution")
                await self.telegram.send_text(render_followup(sig, "TP3 reached — signal resolved."))
                self.active.pop(sig_id, None)
                continue
            if _stop_hit(sig.side, current_price, state.effective_invalidation):
                reason = "breakeven_stop" if state.tp_hits >= 1 else "invalidation"
                state.state = SignalLifecycleState.STOPPED
                await self.store.upsert_signal(sig, state=state.state.value, outcome_note=reason)
                await self.telegram.send_text(render_followup(sig, f"{reason.replace('_', ' ')} triggered."))
                self.active.pop(sig_id, None)
                continue
            if state.tp_hits == 0 and _regime_flipped(sig.side, regime):
                state.state = SignalLifecycleState.EXITED_EARLY
                await self.store.upsert_signal(sig, state=state.state.value, outcome_note="regime_flip_exit")
                await self.telegram.send_text(render_followup(sig, "Regime flipped against the signal — consider closing early."))
                self.active.pop(sig_id, None)
                continue
            if sig.expires_at and sig.expires_at <= datetime.now(tz=timezone.utc):
                state.state = SignalLifecycleState.EXPIRED
                await self.store.upsert_signal(sig, state=state.state.value, outcome_note="expired")
                self.active.pop(sig_id, None)


def _tp_hit(sig: SignalIdea, price: float, idx: int) -> bool:
    if idx > len(sig.targets):
        return False
    target = sig.targets[idx - 1]
    if sig.side == Side.LONG:
        return price >= target
    return price <= target


def _stop_hit(side: Side, price: float, invalidation: float) -> bool:
    return price <= invalidation if side == Side.LONG else price >= invalidation


def _regime_flipped(side: Side, regime: RegimeLabel) -> bool:
    if side == Side.LONG:
        return regime in {RegimeLabel.TREND_DOWN, RegimeLabel.STRESSED}
    return regime in {RegimeLabel.TREND_UP, RegimeLabel.STRESSED}
