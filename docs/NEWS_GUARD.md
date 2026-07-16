# NEWS_GUARD

## Sources

The `NewsGuard` class reads two **free** public sources:

1. **RSS**:
   * `https://www.coindesk.com/arc/outboundfeeds/rss/`
   * `https://cointelegraph.com/rss`
   * `https://bitcoinmagazine.com/.rss/full/`
   * `feedparser` is used (BSD-licensed, `feedparser>=6.0.11`).
2. **CryptoPanic** *(optional)* — `https://cryptopanic.com/api/v1/posts/`.
   Used **only** when `TWA_CRYPTOPANIC_PUBLIC_KEY` is configured.

> We do not scrape news sites — RSS is the standard, low-cost, legal
> channel for ingesting public crypto news.

## Classification

`NewsGuard._classify(title)` maps a title to:

* `severity ∈ {0, 0.5, 1.0}`
* `sentiment ∈ [-1, +1]`
* `category ∈ {"general", "sentiment", "high_impact", "critical"}`

Keyword lists are documented in `src/twa/news/guard.py`:

```
CRITICAL_KEYWORDS = ["hack","exploit","rug pull","rugpull","liquidation cascade",
                    "sec charges","ban","regulatory crackdown","outage","delisting",
                    "insolvent","insolvency","halt","breach","stolen","court",
                    "subpoena","investigation","fraud","halt trading","emergency"]

HIGH_KEYWORDS = ["etf approval","etf rejection","approval","rejection","bullish",
                "bearish","rate cut","rate hike","halving","token unlock","burn",
                "buyback","treasury","whale","large transfer","exchange listing",
                "delist"]
```

These are *configurable* through `ENGINEERING_DECISIONS.md` and
`tests/test_news_guard.py`.  Anyone can extend the lists without
touching the orchestrator.

## Dampen mapping

`NewsGuard.dampen_for(symbol)` returns `(dampen ∈ [0.1, 1.0], events)`:

* No recent events in the last 3 hours → `1.0`.
* Any recent CRITICAL event → `0.1`.
* Linear interpolation by max severity.

## Cycle hygiene

* Refresh rate: `TWA_NEWS_REFRESH_S` (default 180s).
* Items older than 12 hours are purged (`NewsGuard.refresh`).
* Deduplication uses a SHA-1 of `url || title`.

## What the engine does **not** claim

Sentiment scores are *keyword-derived heuristics*.  We do not claim
they model natural language.  The guard is meant to *suppress* signals
when major verifiable events are clustered in time, not to predict
outcomes.
