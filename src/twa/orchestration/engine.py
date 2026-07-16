"""The orchestrator — wires every subsystem into a single async loop.

Responsibilities:
  * On each tick (configurable), refresh data + news for the watchlist.
  * Compute features, classify regime, run signal engine.
  * Apply News Guard dampening, ML calibration, and risk verdict.
  * Publish to Telegram (rate-limited).
  * Update health heartbeat.

It does NOT place orders.
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Dict, List, Optional

from twa.config import Settings, get_settings
from twa.data.cache import MarketDataAggregator
from twa.features.cross_exchange import (
    normalise_funding, oi_momentum, orderbook_imbalance, cross_exchange_dispersion,
)
from twa.features.engineering import compute_all
from twa.logging import get_logger
from twa.ml.calibrator import ConfidenceCalibrator, IdentityCalibrator
from twa.models.types import (
    FundingRate, OpenInterest, OrderBook, RegimeLabel, Side, SignalIdea, Timeframe,
)
from twa.monitoring.health import HealthMonitor
from twa.news.guard import NewsGuard
from twa.regime.classifier import assign_weights, classify, regime_confidence
from twa.risk.engine import RiskEngine
from twa.signal.engine import build_factor_vector, compute_signal
from twa.telegram.bot import TelegramBot

log = get_logger("orchestrator")


class Orchestrator:
    """Run the full pipeline on a loop."""

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self.settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.data = MarketDataAggregator(self.settings)
        self.news = NewsGuard(self.settings)
        if self.settings.ml_enabled:
            self.calibrator = ConfidenceCalibrator(self.settings)
            self.calibrator.load()
        else:
            self.calibrator = IdentityCalibrator()
        self.risk = RiskEngine(self.settings)
        self.health = HealthMonitor(self.settings, self.data)
        self.telegram = TelegramBot(self.settings)
        self._running = False
        self._signals_log: List[SignalIdea] = []

    # ---------- lifecycle ----------
    async def start(self) -> None:
        self._running = True
        await self.health.start()
        await self.telegram.start_command_loop()
        log.info("orchestrator.started",
                 symbols=self.settings.symbols, tf=self.settings.timeframe.value)

    async def stop(self) -> None:
        self._running = False
        await self.health.stop()
        await self.telegram.stop()
        await self.data.close()
        log.info("orchestrator.stopped")

    # ---------- main loop ----------
    async def run_forever(self, interval_s: float = 30.0) -> None:
        await self.start()
        try:
            while self._running:
                cycle_start = time.monotonic()
                try:
                    await self._run_cycle()
                except Exception as e:  # noqa: BLE001
                    log.exception("orchestrator.cycle_failed", err=str(e))
                elapsed = time.monotonic() - cycle_start
                await asyncio.sleep(max(0.0, interval_s - elapsed))
        finally:
            await self.stop()

    async def _run_cycle(self) -> None:
        await self.news.refresh()
        for symbol in self.settings.symbols:
            try:
                idea = await self._one_symbol(symbol)
                if idea is not None:
                    self._record(idea)
                    await self.telegram.send_signal(idea)
            except Exception as e:  # noqa: BLE001
                log.warning("orchestrator.symbol_failed", symbol=symbol, err=str(e))

    async def _one_symbol(self, symbol: str) -> Optional[SignalIdea]:
        candles = await self.data.fetch_candles(
            symbol, self.settings.timeframe, limit=self.settings.lookback_bars,
        )
        if not candles:
            return None

        feats = compute_all(candles)
        regime = classify(feats)
        reg_conf = regime_confidence(feats, regime)

        # Cross-exchange factors: funding, basis, OI, OBI.
        funding: Optional[FundingRate] = await self.data.fetch_funding(symbol)
        oi = await self.data.fetch_open_interest(symbol)
        book: Optional[OrderBook] = await self.data.fetch_orderbook(symbol, depth=20)

        # OI delta: average over last two values; we only have the latest here so
        # treat it as 0 in absence of history.  Documented limitation.
        oi_delta = oi_momentum(getattr(oi, "open_interest", None), None)

        overrides = {
            "funding":  normalise_funding(funding),
            "basis":    0.0,        # no consolidated basis feed in free public set
            "oi_delta": float(oi_delta),
            "obi":      float(orderbook_imbalance(book, depth=10)),
        }

        # News dampening.
        nd, events = self.news.dampen_for(symbol)
        # ML calibration multiplier.
        ml_factor = self.calibrator.calibrate(0.5)  # calibrate a midpoint
        sig = compute_signal(
            candles, self.settings.timeframe, overrides,
            regime=regime, regime_conf=reg_conf,
            news_dampen=nd, ml_calibration=ml_factor,
        )
        if sig is None:
            return None
        sig.news_dampen = nd
        sig.news_events = events

        verdict = self.risk.evaluate(
            sig,
            news_dampen=nd,
            ml_calibration=ml_factor,
            high_volatility=feats.get("realised_vol_30", 0.0) >= 0.85,
            stressed_regime=regime == RegimeLabel.STRESSED,
        )
        if not verdict.accepted:
            log.debug("orchestrator.risk_rejected", symbol=symbol, reason=verdict.reason)
            return None
        # overwrite signal confidence with calibrated one
        sig.confidence = float(verdict.adjusted_confidence)
        return sig

    # ---------- accounting ----------
    def _record(self, sig: SignalIdea) -> None:
        self._signals_log.append(sig)
        if len(self._signals_log) > 2000:
            self._signals_log = self._signals_log[-2000:]
        out_path = self.settings.data_dir / "signals.jsonl"
        try:
            with out_path.open("a", encoding="utf-8") as f:
                f.write(sig.model_dump_json() + "\n")
        except Exception as e:  # noqa: BLE001
            log.warning("orchestrator.persist_failed", err=str(e))

    def recent_signals(self, n: int = 10) -> List[SignalIdea]:
        return self._signals_log[-n:]
