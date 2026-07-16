# API_REFERENCE

## CLI

```
twa run                   [--symbols BTCUSDT,ETHUSDT] [--timeframe 1h] [--interval 30]
twa paper                 --symbol BTCUSDT [--timeframe 1h]
twa backtest              --symbol BTCUSDT [--timeframe 1h] [--days 30]
twa signals               [--limit 10]
twa health
twa config
```

## Programmatic surface

```python
from twa.config import get_settings
from twa.data.cache import MarketDataAggregator
from twa.features.engineering import compute_all, list_features
from twa.regime.classifier import classify, assign_weights, regime_confidence
from twa.signal.engine import compute_signal, build_factor_vector
from twa.risk.engine import RiskEngine
from twa.news.guard import NewsGuard
from twa.telegram.bot import render_signal, TelegramBot
from twa.orchestration.engine import Orchestrator
```

## Telegram messages

* `/signal` — last 5 emitted signals (admin only).
* `/health` — adapter health summary.
* `/config` — effective configuration snapshot.

## Data endpoint examples

```bash
# Binance — public (no auth)
curl 'https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1h&limit=2'
# Bybit — public (no auth)
curl 'https://api.bybit.com/v5/market/kline?category=linear&symbol=BTCUSDT&interval=60&limit=2'
# Coinbase — public (no auth)
curl 'https://api.exchange.coinbase.com/products/BTC-USD/candles?granularity=3600'
```
