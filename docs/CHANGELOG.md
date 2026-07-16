# CHANGELOG

## 1.0.0 — TRADE WITH ARUN — first production release

Highlights
* Async-first crypto derivatives **signal** engine.
* Free public data adapters: Binance (spot + USDⓈ-M perpetuals), Bybit v5, Coinbase Exchange.
* 8-feature engineered catalogue; deterministic regime classifier.
* Multi-factor signal engine with explainable per-factor contributions.
* Institutional-quality risk engine with cooldowns, exposure and dampeners.
* News Guard (RSS + optional CryptoPanic).
* ML confidence calibrator with transparent identity fallback.
* Backtest harness with Monte Carlo — **never fabricates numbers**.
* Premium Telegram experience.
* Health monitor with heartbeat, CPU/RSS/feed health.
* CLI: `twa run|paper|backtest|signals|health|config`.
* 14-test suite (`pytest -q`) confirms contract.
* Cross-platform (Linux + Windows) — async, no thread-blocking.
