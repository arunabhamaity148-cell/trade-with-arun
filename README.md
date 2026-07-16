# TRADE WITH ARUN

> Institutional-grade crypto derivatives **signal engine** (signal-only; **no order placement**).
> Production-ready, async-first, fully typed, Pydantic-validated, free public data only.

## What it does
- Pulls **free** market data from Binance, Bybit, Coinbase and CoinGecko public endpoints
- Engineers microstructure features (funding, basis, OI, OBI, liquidation bursts, realised vol)
- Classifies the market regime (trend / range / volatile / stressed) and adapts signal weights
- Produces multi-factor, explainable trade ideas with confidence, risk and invalidation levels
- Filters signals through a News Guard (free public sources + RSS) and an ML calibrator
- Telegram UX with admin / health / statistics commands
- Health + heartbeat + memory + CPU monitoring; graceful shutdown
- Honest backtest framework with walk-forward and Monte Carlo. **No performance is fabricated.**

## What it does NOT do
- **It does not place orders.** It only produces explainable trade ideas.

## Quick start
```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,ml]"
cp .env.example .env  # then edit values
pytest -q
twa run --symbols BTCUSDT,ETHUSDT --timeframe 1h
twa paper --symbol BTCUSDT --timeframe 15m
twa backtest --symbol BTCUSDT --timeframe 1h --days 90
```

## Folder layout
See `docs/PROJECT_STRUCTURE.md`.

## Disclaimer
This software is research/educational software. It produces signals, not investment advice.
Cryptocurrency derivatives trading carries substantial risk of loss.
