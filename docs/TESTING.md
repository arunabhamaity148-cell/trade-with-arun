# TESTING

Test suite layout lives under `tests/`.  Tests are written with
`pytest`, `pytest-asyncio`, and a deterministic synthetic candle
generator (`tests/conftest.py`).

## Run

```bash
pytest -q
```

## Categories

| Test file | Covers |
|-----------|--------|
| `test_config.py` | Settings validation, env parsing |
| `test_models.py` | Pydantic validation, types |
| `test_features.py` | Feature catalogue, cross-exchange helpers |
| `test_regime.py` | Classifier, weights, HMM fallback |
| `test_signal_engine.py` | Score → confidence pipeline |
| `test_risk_engine.py` | Cooldowns, exposure, dampeners |
| `test_news_guard.py` | Classification, dampen mapping |
| `test_backtest.py` | Honesty invariants |
| `test_telegram.py` | Premium rendering |
| `test_data_adapters_shapes.py` | Adapter structural contracts |
| `test_ml_calibrator.py` | Calibrator identity / fallback |
| `test_orchestrator_integration.py` | End-to-end with synthetic feed |

## Honesty tests

`tests/test_backtest.py` asserts:
* Empty / too-short candle lists return `INSUFFICIENT_DATA`.
* A small backtest with < 30 trades prints `INSUFFICIENT_TRADES`.
* `summary()` reports `win_rate=None` until the 30-trade threshold.

The product code never fakes `win_rate`.
