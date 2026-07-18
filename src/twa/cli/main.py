"""CLI for `twa`.

Sub-commands:
  run       — run the full orchestrator (live/paper loop)
  paper     — run a single paper pass for one symbol (no persistence, prints JSON)
  backtest  — run a backtest on a symbol's history (uses binance or bybit)
  signals   — list recent persisted signals from data/signals.jsonl
  health    — write a one-shot heartbeat
  config    — print effective config
  research  — research and benchmarking workflows
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Optional

from twa import __version__
from twa.config import get_settings, reload_settings, Settings
from twa.logging import configure_logging, get_logger
from twa.data.cache import MarketDataAggregator
from twa.features.engineering import compute_all
from twa.features.cross_exchange import normalise_funding, oi_momentum, orderbook_imbalance
from twa.models.types import SignalEntryState, Timeframe, coerce_timeframe
from twa.monitoring.health import HealthMonitor
from twa.news.guard import NewsGuard
from twa.orchestration.engine import Orchestrator
from twa.regime.classifier import classify, regime_confidence
from twa.signal.engine import compute_signal, engine_config_from_settings

log = get_logger("cli")

PROGRAM = f"\n██████  TRADE WITH ARUN  ██████\n  Crypto derivatives SIGNAL ENGINE — v{__version__}\n"


def cmd_run(args: argparse.Namespace) -> int:
    cfg = _select_settings(get_settings(), args)
    configure_logging(cfg.log_level)
    print(PROGRAM)
    log.info("cli.run.begin", symbols=cfg.symbols, timeframe=cfg.timeframe)
    orch = Orchestrator(cfg)
    try:
        asyncio.run(orch.run_forever(interval_s=args.interval))
    except KeyboardInterrupt:
        log.info("cli.run.interrupted")
    return 0


def cmd_paper(args: argparse.Namespace) -> int:
    cfg = _select_settings(get_settings(), args)
    configure_logging(cfg.log_level)
    print(PROGRAM)
    return asyncio.run(_paper(cfg, args.symbol, args.timeframe))


async def _paper(cfg: Settings, symbol: str, timeframe_str: str) -> int:
    timeframe = coerce_timeframe(timeframe_str)
    data = MarketDataAggregator(cfg)
    news = NewsGuard(cfg)
    try:
        await news.refresh()
        candles = await data.fetch_candles(symbol, timeframe, limit=cfg.lookback_bars)
        if not candles:
            print(json.dumps({"error": "no_candles", "symbol": symbol, "exchange": data.health()}, indent=2))
            return 2
        funding = await data.fetch_funding(symbol)
        oi = await data.fetch_open_interest(symbol)
        book = await data.fetch_orderbook(symbol, depth=20)

        feats = compute_all(candles)
        regime = classify(feats)
        reg_conf = regime_confidence(feats, regime)
        nd, events = news.dampen_for(symbol)
        overrides = {
            "funding": normalise_funding(funding),
            "basis": 0.0,
            "oi_delta": oi_momentum(getattr(oi, "open_interest", None), None),
            "obi": orderbook_imbalance(book, depth=10),
        }
        sig = compute_signal(
            candles,
            timeframe,
            overrides,
            regime,
            reg_conf,
            cfg=engine_config_from_settings(cfg),
            news_dampen=nd,
            ml_calibration=1.0,
        )
        if sig is None:
            print(json.dumps({"symbol": symbol, "regime": regime.value, "confidence": reg_conf,
                              "note": "BELOW_MINIMUM_THRESHOLD"}, indent=2, default=str))
            return 0
        sig.news_dampen = nd
        sig.news_events = events
        if not cfg.sniper_enabled:
            sig.entry_state = SignalEntryState.ENTER_NOW
            sig.entry_trigger = "sniper_disabled"
            sig.max_wait_bars = 0
        print(json.dumps(sig.model_dump(), indent=2, default=str))
        return 0
    finally:
        await data.close()


def cmd_backtest(args: argparse.Namespace) -> int:
    cfg = _select_settings(get_settings(), args)
    configure_logging(cfg.log_level)
    print(PROGRAM)
    return asyncio.run(_backtest(cfg, args.symbol, args.timeframe, args.days))


async def _backtest(cfg: Settings, symbol: str, timeframe_str: str, days: int) -> int:
    from twa.backtest.replay import simulate, monte_carlo

    timeframe = coerce_timeframe(timeframe_str)
    data = MarketDataAggregator(cfg)
    try:
        need = {"1m": 60 * 24 * days, "5m": 12 * 24 * days, "15m": 4 * 24 * days,
                "1h": 24 * days, "4h": 6 * days, "1d": days}[timeframe.value]
        limit = min(1000, max(50, need))
        candles = await data.fetch_candles(symbol, timeframe, limit=limit)
        if len(candles) < 60:
            print("NOT_ENOUGH_HISTORY")
            return 2
        result = simulate(
            candles,
            timeframe,
            factor_overrides_list=[{}] * len(candles),
            settings=cfg,
            cfg=engine_config_from_settings(cfg),
            sniper_entry=cfg.sniper_enabled,
        )
        summary = result.summary()
        summary["monte_carlo"] = monte_carlo(result.trades)
        summary["honesty"] = (
            "No live validation has been performed. Numerical results below are produced "
            "from the supplied historical snippet; do not extrapolate beyond the declared window."
        )
        print(json.dumps(summary, indent=2, default=str))
        return 0
    finally:
        await data.close()


def cmd_signals(args: argparse.Namespace) -> int:
    cfg = get_settings()
    p = cfg.data_dir / "signals.jsonl"
    if not p.exists():
        print("NO_SIGNALS")
        return 0
    lines = p.read_text(encoding="utf-8").splitlines()[-args.limit:]
    print("\n".join(lines))
    return 0


def cmd_health(args: argparse.Namespace) -> int:  # noqa: ARG001
    cfg = get_settings()
    configure_logging(cfg.log_level)
    print(PROGRAM)
    print(json.dumps(asyncio.run(_health_once(cfg)), indent=2, default=str))
    return 0


async def _health_once(cfg: Settings) -> dict:
    data = MarketDataAggregator(cfg)
    try:
        await data.probe(timeframe=coerce_timeframe(cfg.timeframe))
        health = HealthMonitor(cfg, data)
        await health.tick()
        return health.snapshot()
    finally:
        await data.close()


def cmd_config(args: argparse.Namespace) -> int:  # noqa: ARG001
    cfg = reload_settings()
    print(PROGRAM)
    print(json.dumps(_redacted_settings(cfg), indent=2, default=str))
    return 0


def cmd_research_run_experiment(args: argparse.Namespace) -> int:
    cfg = _select_settings(get_settings(), args)
    configure_logging(cfg.log_level)
    print(PROGRAM)
    return asyncio.run(_research_run_experiment(cfg, Path(args.config)))


async def _research_run_experiment(cfg: Settings, config_path: Path) -> int:
    from twa.research.experiment_runner import ExperimentRunner

    runner = ExperimentRunner(cfg)
    try:
        result = await runner.run_config_path(config_path)
        print(json.dumps(result.model_dump(), indent=2, default=str))
        return 0
    finally:
        await runner.close()


def cmd_research_benchmark(args: argparse.Namespace) -> int:
    cfg = _select_settings(get_settings(), args)
    configure_logging(cfg.log_level)
    print(PROGRAM)
    return asyncio.run(_research_benchmark(cfg, args.symbol, args.timeframe, args.days))


async def _research_benchmark(cfg: Settings, symbol: str, timeframe_str: str, days: int) -> int:
    from twa.research.benchmarking import BenchmarkConfig, BenchmarkRunner

    runner = BenchmarkRunner(cfg)
    try:
        report = await runner.run(
            symbol=symbol,
            timeframe=coerce_timeframe(timeframe_str),
            days=days,
            config=BenchmarkConfig(),
        )
        print(json.dumps(report.model_dump(), indent=2, default=str))
        return 0
    finally:
        await runner.close()


def _redacted_settings(cfg: Settings) -> dict:
    payload = cfg.model_dump(mode="json")
    for key in ("telegram_bot_token", "telegram_chat_id", "cryptopanic_public_key"):
        if payload.get(key):
            payload[key] = "***REDACTED***"
    return payload


def _select_settings(base: Settings, args: argparse.Namespace) -> Settings:
    overrides = {}
    if getattr(args, "symbols", None):
        symbols = args.symbols
        if isinstance(symbols, str):
            overrides["symbols"] = [s.strip() for s in symbols.split(",") if s.strip()]
        else:
            overrides["symbols"] = symbols
    if getattr(args, "timeframe", None):
        overrides["timeframe"] = args.timeframe
    if overrides:
        return base.model_copy(update=overrides)
    return base


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="twa", description="TRADE WITH ARUN — crypto signal engine")
    p.add_argument("--version", action="version", version=f"twa {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("run", help="run the full async orchestrator (paper or live)")
    sp.add_argument("--symbols", help="comma-separated symbols, e.g. BTCUSDT,ETHUSDT")
    sp.add_argument("--timeframe", choices=["1m", "5m", "15m", "1h", "4h", "1d"])
    sp.add_argument("--interval", type=float, default=30.0)
    sp.set_defaults(fn=cmd_run)

    sp = sub.add_parser("paper", help="run one signal pass and print JSON")
    sp.add_argument("--symbol", default="BTCUSDT")
    sp.add_argument("--timeframe", default="1h", choices=["1m", "5m", "15m", "1h", "4h", "1d"])
    sp.set_defaults(fn=cmd_paper)

    sp = sub.add_parser("backtest", help="run a backtest over the last N days")
    sp.add_argument("--symbol", default="BTCUSDT")
    sp.add_argument("--timeframe", default="1h", choices=["1m", "5m", "15m", "1h", "4h", "1d"])
    sp.add_argument("--days", type=int, default=30)
    sp.set_defaults(fn=cmd_backtest)

    sp = sub.add_parser("signals", help="print recently persisted signals")
    sp.add_argument("--limit", type=int, default=10)
    sp.set_defaults(fn=cmd_signals)

    sp = sub.add_parser("health", help="one-shot heartbeat")
    sp.set_defaults(fn=cmd_health)

    sp = sub.add_parser("config", help="print effective configuration")
    sp.set_defaults(fn=cmd_config)

    sp = sub.add_parser("research", help="research lab workflows")
    research_sub = sp.add_subparsers(dest="research_cmd", required=True)

    rsp = research_sub.add_parser("run-experiment", help="run a declarative research experiment")
    rsp.add_argument("--config", required=True)
    rsp.add_argument("--timeframe", choices=["1m", "5m", "15m", "1h", "4h", "1d"])
    rsp.set_defaults(fn=cmd_research_run_experiment)

    rsp = research_sub.add_parser("benchmark", help="benchmark production vs baselines")
    rsp.add_argument("--symbol", default="BTCUSDT")
    rsp.add_argument("--timeframe", default="1h", choices=["1m", "5m", "15m", "1h", "4h", "1d"])
    rsp.add_argument("--days", type=int, default=30)
    rsp.set_defaults(fn=cmd_research_benchmark)

    return p


def main(argv: Optional[list] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
