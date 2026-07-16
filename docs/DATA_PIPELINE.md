# DATA_PIPELINE

> All feeds are **free**, **public**, **no authentication**, **HTTPS**.
> Endpoints are documented inline at the top of each adapter.

## Sources

| Exchange | Endpoint family | Auth | What we use |
|----------|-----------------|------|------------|
| Binance  | `https://api.binance.com/api/v3/*` (spot),  `https://fapi.binance.com/fapi/v1/*` (USDⓈ-M perp) | none (public market data) | klines, ticker, depth, funding, open-interest |
| Bybit    | `https://api.bybit.com/v5/market/*` | none (public market data) | kline, tickers, orderbook, funding-history, open-interest |
| Coinbase | `https://api.exchange.coinbase.com` | none (Exchange public endpoints) | BTC & ETH spot klines, ticker, book |

References used during research / implementation:

* Binance developers docs (USDⓈ-M streams) — `developers.binance.com`
* Bybit v5 docs (`/v5/market/kline`, `/v5/market/funding/history`,
  `/v5/market/open-interest`)
* Coinbase Exchange developer docs (`docs.cdp.coinbase.com/exchange`)

> We did *not* invent endpoints — every URL is documented in the
> adapter comments.  The exchange public APIs that we use do not
> require authentication for read-only market data, as confirmed by
> their docs and `vezgo.com/blog/bybit-api-cheat-sheet`.

## Pipelining

* The `MarketDataAggregator.fetch_candles()` method queries every
  healthy adapter concurrently.
* A TTL cache (`TTLCache`, default 15s) prevents duplicate work on
  hot paths.
* Cross-exchange *price dispersion* is logged when it exceeds 10%
  (this is non-fatal; aggregation still proceeds).

## Validation

Every `Candle` is passed through Pydantic validators:
* Timestamps normalised to UTC.
* Prices/volumes must be finite (`-inf`, `+inf`, `NaN` → rejected).
* Repeated timestamp series are de-duplicated by open-time.

## Stale-feed detection

* Each adapter records `last_ok_ts` (epoch seconds) on success.
* Any caller using `_gather_first` skips adapters whose last successful
  fetch is older than `STALE_AFTER_S` (default 120s).  If all adapters
  are stale, the aggregator still attempts the call (best-effort).

## Storage

Nothing is written to disk in the hot path except:
* `data_dir/heartbeat.json` — health snapshot (small, periodic).
* `data_dir/signals.jsonl` — append-only signal log.

Across restarts the log is read back into memory only when an
operator explicitly requests it (`twa signals`).
