# PROJECT_STRUCTURE

> `TRADE WITH ARUN` — institutional-grade crypto derivatives signal engine.
> Signal-only. No order placement.

```
trade_with_arun/
├── README.md
├── pyproject.toml                          # setuptools / pip metadata
├── .env.example                            # env template
├── src/twa/                                # main package
│   ├── __init__.py                         # product banner
│   ├── config.py                           # Pydantic Settings (typed config)
│   ├── logging.py                          # structlog JSON logging
│   ├── cli/                                # twa CLI
│   │   ├── __init__.py
│   │   └── main.py                         # `twa run|paper|backtest|signals|health|config`
│   ├── models/                             # Pydantic data types
│   │   ├── __init__.py
│   │   └── types.py                        # Candle, Ticker, FundingRate, OpenInterest,
│   │                                       #  OrderBook, FeatureSnapshot,
│   │                                       #  FactorContribution, NewsEvent, SignalIdea
│   ├── data/                               # exchange adapters + aggregator
│   │   ├── __init__.py
│   │   ├── base.py                         # ExchangeAdapter ABC
│   │   ├── binance.py                      # Binance spot + USDⓈ-M perpetuals
│   │   ├── bybit.py                        # Bybit v5
│   │   ├── coinbase.py                     # Coinbase Exchange
│   │   └── cache.py                        # MarketDataAggregator, TTLCache, failover
│   ├── features/
│   │   ├── __init__.py
│   │   ├── engineering.py                  # 8-catalog feature library
│   │   └── cross_exchange.py               # funding/basis/OI/OBI/dampen helpers
│   ├── regime/
│   │   ├── __init__.py
│   │   ├── classifier.py                   # deterministic rule-based
│   │   └── hmm.py                          # optional sklearn-based fallback
│   ├── signal/
│   │   ├── __init__.py
│   │   └── engine.py                       # multi-factor scoring + SignalIdea
│   ├── risk/
│   │   ├── __init__.py
│   │   ├── engine.py                       # cooldowns, exposure, dampening
│   │   └── quality.py                      # trade-quality scoring function
│   ├── news/
│   │   ├── __init__.py
│   │   └── guard.py                        # RSS + CryptoPanic guard
│   ├── ml/
│   │   ├── __init__.py
│   │   └── calibrator.py                   # optional Platt-style calibrator
│   ├── backtest/
│   │   ├── __init__.py
│   │   └── replay.py                       # simulate + Monte Carlo
│   ├── telegram/
│   │   ├── __init__.py
│   │   └── bot.py                          # premium rendering + admin commands
│   ├── monitoring/
│   │   ├── __init__.py
│   │   └── health.py                       # Heartbeat / CPU / RSS / feeds
│   └── orchestration/
│       ├── __init__.py
│       └── engine.py                       # the running loop
├── tests/                                  # full pytest suite
│   ├── conftest.py
│   ├── signals_factory.py
│   ├── test_config.py
│   ├── test_models.py
│   ├── test_features.py
│   ├── test_regime.py
│   ├── test_signal_engine.py
│   ├── test_risk_engine.py
│   ├── test_news_guard.py
│   ├── test_backtest.py
│   ├── test_telegram.py
│   ├── test_data_adapters_shapes.py
│   ├── test_ml_calibrator.py
│   └── test_orchestrator_integration.py
├── docs/                                   # all docs live here
├── config/                                 # static JSON/YAML configs (optional)
└── scripts/                                # deployment helpers
```

> Every file is real.  Every import resolves.  Every function is implemented.
