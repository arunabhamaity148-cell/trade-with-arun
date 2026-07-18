"""The orchestrator — wires every subsystem into a single async loop.

Responsibilities:
  * On each tick, refresh data + news for the watchlist.
  * Compute features, classify regime, run signal engine.
  * Apply News Guard dampening, ML calibration, and risk verdict exactly once.
  * Publish to Telegram (rate-limited).
  * Update health heartbeat.

It does NOT place orders.
"""
from __future__ import annotations

import asyncio
import json
import signal
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

from twa.config import Settings, get_settings
from twa.data.cache import MarketDataAggregator
from twa.features.cross_exchange import normalise_funding, oi_momentum, orderbook_imbalance
from twa.features.engineering import compute_all
from twa.logging import get_logger
from twa.ml.calibrator import ConfidenceCalibrator, IdentityCalibrator
from twa.models.types import FundingRate, OpenInterest, OrderBook, RegimeLabel, SignalEntryState, SignalIdea, Timeframe, coerce_timeframe
from twa.monitoring.health import HealthMonitor
from twa.news.guard import NewsGuard
from twa.regime.classifier import classify, regime_confidence
from twa.risk.engine import RiskEngine
from twa.signal.engine import compute_signal, engine_config_from_settings
from twa.signal.lifecycle import SignalLifecycleManager
from twa.signal.store import SignalOutcomeStore
from twa.telegram.bot import TelegramBot

log = get_logger("orchestrator")


@dataclass
class OICacheEntry:
    open_interest: float
    timestamp: float


class OICache:
    def __init__(self, ttl_s: float = 8 * 3600.0):
        self.ttl_s = ttl_s
        self._entries: Dict[str, OICacheEntry] = {}

    def previous(self, key: str, *, now_ts: float) -> Optional[float]:
        entry = self._entries.get(key)
        if entry is None:
            return None
        if now_ts - entry.timestamp > self.ttl_s:
            self._entries.pop(key, None)
            return None
        return entry.open_interest

    def update(self, key: str, current_oi: Optional[float], *, now_ts: float) -> None:
        if current_oi is None:
            return
        self._entries[key] = OICacheEntry(open_interest=float(current_oi), timestamp=now_ts)


class Orchestrator:
    """Run the full pipeline on a loop."""

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self.timeframe = coerce_timeframe(self.settings.timeframe)
        self.engine_cfg = engine_config_from_settings(self.settings)
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
        self.store = SignalOutcomeStore(self.settings)
        self.lifecycle = SignalLifecycleManager(self.store, self.telegram, risk_engine=self.risk)
        self._running = False
        self._signals_log: List[SignalIdea] = []
        self._oi_cache = OICache()
        self._install_signal_handlers_requested = False

    async def start(self) -> None:
        self._running = True
        await self.health.start()
        await self.telegram.start_command_loop()
        await self.lifecycle.start()
        self._install_signal_handlers()
        self._update_telegram_context()
        log.info("orchestrator.started", symbols=self.settings.symbols, tf=self.timeframe.value)

    async def stop(self) -> None:
        self._running = False
        await self.health.stop()
        await self.telegram.stop()
        await self.lifecycle.stop()
        await self.data.close()
        log.info("orchestrator.stopped")

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
                    await self.lifecycle.register_candidate(idea)
            except Exception as e:  # noqa: BLE001
                log.warning("orchestrator.symbol_failed", symbol=symbol, err=str(e))
        self._update_telegram_context()

    async def _one_symbol(self, symbol: str) -> Optional[SignalIdea]:
        candles = await self.data.fetch_candles(symbol, self.timeframe, limit=self.settings.lookback_bars)
        if not candles:
            return None

        last_price = float(candles[-1].close)
        feats = compute_all(candles)
        regime = classify(feats)
        reg_conf = regime_confidence(feats, regime)

        funding: Optional[FundingRate] = await self.data.fetch_funding(symbol)
        oi: Optional[OpenInterest] = await self.data.fetch_open_interest(symbol)
        book: Optional[OrderBook] = await self.data.fetch_orderbook(symbol, depth=20)

        current_ts = time.time()
        oi_key = f"{symbol}|{getattr(oi, 'exchange', 'unknown')}"
        prior_oi = self._oi_cache.previous(oi_key, now_ts=current_ts)
        current_oi = getattr(oi, "open_interest", None)
        oi_delta = oi_momentum(current_oi, prior_oi)
        self._oi_cache.update(oi_key, current_oi, now_ts=current_ts)
        basis = await self._compute_basis(symbol)

        overrides = {
            "funding": normalise_funding(funding),
            "basis": float(basis),
            "oi_delta": float(oi_delta),
            "obi": float(orderbook_imbalance(book, depth=10)),
        }

        self.news.update_market_context(symbol, candles)
        assessment = self.news.assess(symbol)
        await self.lifecycle.update_price(symbol, last_price, regime)
        for sig_id in list(self.lifecycle.candidates):
            candidate = self.lifecycle.candidates[sig_id]
            if candidate.signal.symbol == symbol:
                await self.lifecycle.try_activate_candidate(sig_id, last_price)
        if assessment.signal_cancelled:
            log.info("orchestrator.signal_cancelled_by_news", symbol=symbol, reasons=assessment.reasons)
            return None

        sig = compute_signal(candles, self.timeframe, overrides, regime=regime, regime_conf=reg_conf, cfg=self.engine_cfg)
        if sig is None:
            return None
        raw_conf = float(sig.raw_confidence if sig.raw_confidence is not None else sig.confidence)
        ml_factor = self.calibrator.calibrate(raw_conf)
        sig.news_dampen = assessment.confidence_multiplier
        sig.ml_calibration = ml_factor
        sig.news_events = self.news.surface_events(symbol)

        verdict = self.risk.evaluate(
            sig,
            news_dampen=assessment.confidence_multiplier,
            ml_calibration=ml_factor,
            high_volatility=feats.get("realised_vol_30", 0.0) >= 0.95,
            stressed_regime=regime == RegimeLabel.STRESSED,
        )
        if not verdict.accepted:
            log.debug("orchestrator.risk_rejected", symbol=symbol, reason=verdict.reason)
            return None

        sig.final_confidence = float(verdict.adjusted_confidence)
        sig.confidence = float(verdict.adjusted_confidence)
        sig.basis = float(basis)
        sig.oi_delta = float(oi_delta)
        if not self.settings.sniper_enabled:
            sig.entry_state = SignalEntryState.ENTER_NOW
            sig.entry_trigger = "sniper_disabled"
            sig.max_wait_bars = 0
        return sig

    async def _compute_basis(self, symbol: str) -> float:
        spot, perp = await asyncio.gather(self._fetch_spot_reference(symbol), self._fetch_perp_reference(symbol))
        if spot is None or perp is None or spot <= 0:
            return 0.0
        return float(max(-1.0, min(1.0, (perp - spot) / spot)))

    async def _fetch_spot_reference(self, symbol: str) -> Optional[float]:
        adapters = getattr(self.data, "adapters", {}) or {}
        coinbase = adapters.get("coinbase")
        if coinbase is not None:
            try:
                ticker = await coinbase.fetch_ticker(symbol)
                if ticker is not None and ticker.last > 0:
                    return float(ticker.last)
            except Exception:  # noqa: BLE001
                pass
        try:
            ticker = await self.data.fetch_ticker(symbol)
            if ticker is not None and ticker.exchange == "coinbase" and ticker.last > 0:
                return float(ticker.last)
        except Exception:  # noqa: BLE001
            pass
        return None

    async def _fetch_perp_reference(self, symbol: str) -> Optional[float]:
        adapters = getattr(self.data, "adapters", {}) or {}
        for name in ("binance", "bybit"):
            adapter = adapters.get(name)
            if adapter is None:
                continue
            try:
                ticker = await adapter.fetch_ticker(symbol)
            except Exception:  # noqa: BLE001
                ticker = None
            if ticker is not None and ticker.last > 0:
                return float(ticker.last)
        return None

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

    def _update_telegram_context(self) -> None:
        app = getattr(self.telegram, "_app", None)
        if app is None:
            return
        app.bot_data["signals"] = self.recent_signals(20)
        app.bot_data["health"] = self.health.snapshot()
        payload = self.settings.model_dump(mode="json")
        for key in ("telegram_bot_token", "telegram_chat_id", "cryptopanic_public_key"):
            if payload.get(key):
                payload[key] = "***REDACTED***"
        app.bot_data["config_text"] = json.dumps(payload, sort_keys=True)

    def _install_signal_handlers(self) -> None:
        if self._install_signal_handlers_requested:
            return
        self._install_signal_handlers_requested = True
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        def _request_stop() -> None:
            log.info("orchestrator.shutdown_requested")
            self._running = False

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, _request_stop)
            except (NotImplementedError, RuntimeError):
                continue
