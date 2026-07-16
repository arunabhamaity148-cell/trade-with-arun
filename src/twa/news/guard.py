"""News Guard — classify crypto news and dampen/suppress signals.

Sources (all free, public):
  * CryptoPanic public API (https://cryptopanic.com/developers/api/) — optional, free public key.
  * RSS feeds from multiple reputable outlets (CoinDesk, Cointelegraph, Bitcoin Magazine, etc.).

The guard:
  1. Pulls recent items each cycle, deduplicates.
  2. Scores each item by keyword-based severity & sentiment.
  3. Maps items to symbols; aggregates per-symbol severity.
  4. Returns a per-symbol *dampen factor* ∈ [0.1, 1.0] used by the risk engine.
"""
from __future__ import annotations

import asyncio
import hashlib
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import feedparser
import httpx

from twa.config import Settings
from twa.logging import get_logger
from twa.models.types import NewsEvent

log = get_logger("news")

CRITICAL_KEYWORDS = [
    "hack", "exploit", "rug pull", "rugpull", "liquidation cascade", "sec charges",
    "ban", "regulatory crackdown", "outage", "delisting", "insolvent", "insolvency",
    "halt", "breach", "stolen", "court", "subpoena", "investigation", "fraud",
    "halt trading", "emergency",
]
HIGH_KEYWORDS = [
    "etf approval", "etf rejection", "approval", "rejection", "bullish", "bearish",
    "rate cut", "rate hike", "halving", "token unlock", "burn", "buyback",
    "treasury", "whale", "large transfer", "exchange listing", "delist",
]
SYMBOL_PATTERNS = {
    "BTCUSDT": [r"\bbtc\b", r"\bbitcoin\b"],
    "ETHUSDT": [r"\beth\b", r"\bethereum\b"],
    "SOLUSDT": [r"\bsol\b", r"\bsolana\b"],
    "BNBUSDT": [r"\bbnb\b", r"\bbinance coin\b"],
    "XRPUSDT": [r"\bxrp\b", r"\bripple\b"],
    "DOGEUSDT": [r"\bdoge\b", r"\bdogecoin\b"],
    "ADAUSDT": [r"\bada\b", r"\bcardano\b"],
}

SEVERE_RSS_FEEDS = [
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "https://cointelegraph.com/rss",
    "https://bitcoinmagazine.com/.rss/full/",
]


@dataclass
class NewsGuard:
    settings: Settings
    _cache: List[NewsEvent] = field(default_factory=list)
    _last_fetch: float = 0.0
    _seen: set = field(default_factory=set)

    async def refresh(self) -> None:
        """Refresh news from configured sources if cooldown elapsed."""
        if not self.settings.news_enabled:
            return
        if time.time() - self._last_fetch < self.settings.news_refresh_s:
            return
        self._last_fetch = time.time()
        events: List[NewsEvent] = []
        if "rss" in self.settings.news_sources:
            events.extend(await self._fetch_rss())
        if "cryptopanic" in self.settings.news_sources and self.settings.cryptopanic_public_key:
            events.extend(await self._fetch_cryptopanic())
        for ev in events:
            h = hashlib.sha1((ev.url or ev.title).encode()).hexdigest()
            if h in self._seen:
                continue
            self._seen.add(h)
            self._cache.append(ev)
        cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=12)
        self._cache = [e for e in self._cache if e.published_at >= cutoff]
        log.debug("news.refresh", new=len(events), cached=len(self._cache))

    async def _fetch_rss(self) -> List[NewsEvent]:
        events: List[NewsEvent] = []
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            for url in SEVERE_RSS_FEEDS:
                try:
                    r = await client.get(url)
                    r.raise_for_status()
                except Exception as e:  # noqa: BLE001
                    log.debug("news.rss.fetch_failed", url=url, err=str(e))
                    continue
                feed = feedparser.parse(r.text)
                for entry in feed.entries[:30]:
                    try:
                        published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                    except Exception:
                        published = datetime.now(tz=timezone.utc)
                    title = entry.get("title", "") or ""
                    link = entry.get("link", "") or ""
                    sev, sent, cat = self._classify(title)
                    syms = self._detect_symbols(title)
                    events.append(NewsEvent(
                        title=title[:300], source=feed.feed.get("title", url),
                        url=link, published_at=published,
                        symbols=syms, severity=sev, sentiment=sent, category=cat,
                    ))
        return events

    async def _fetch_cryptopanic(self) -> List[NewsEvent]:
        url = "https://cryptopanic.com/api/v1/posts/"
        params = {"public": "true", "kind": "news"}
        if self.settings.cryptopanic_public_key:
            params["auth_token"] = self.settings.cryptopanic_public_key
        out: List[NewsEvent] = []
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                r = await client.get(url, params=params)
                r.raise_for_status()
                data = r.json()
        except Exception as e:  # noqa: BLE001
            log.warning("news.cryptopanic.fetch_failed", err=str(e))
            return out
        for item in data.get("results", [])[:30]:
            title = item.get("title", "")
            link = item.get("url", "")
            published = datetime.fromisoformat(
                item.get("published_at", datetime.now(tz=timezone.utc).isoformat())
            )
            if published.tzinfo is None:
                published = published.replace(tzinfo=timezone.utc)
            sev, sent, cat = self._classify(title)
            syms = []
            for c in item.get("currencies", []) or []:
                code = c.get("code", "").upper()
                if code:
                    syms.append(code + "USDT")
            out.append(NewsEvent(
                title=title[:300], source="cryptopanic",
                url=link, published_at=published,
                symbols=syms, severity=sev, sentiment=sent, category=cat,
            ))
        return out

    def _classify(self, text: str) -> Tuple[float, float, str]:
        t = text.lower()
        sev = 0.0
        sent = 0.0
        for k in CRITICAL_KEYWORDS:
            if k in t:
                sev = max(sev, 1.0)
                sent -= 0.4
        for k in HIGH_KEYWORDS:
            if k in t:
                sev = max(sev, 0.5)
        if any(pos in t for pos in ["bullish", "approval", "buyback", "rate cut", "halving"]):
            sent += 0.2
        if any(neg in t for neg in ["bearish", "hack", "exploit", "ban", "rejection", "fraud"]):
            sent -= 0.3
        sent = max(-1.0, min(1.0, sent))
        category = "general"
        if sev >= 1.0:
            category = "critical"
        elif sev >= 0.5:
            category = "high_impact"
        elif sent != 0:
            category = "sentiment"
        return sev, sent, category

    def _detect_symbols(self, text: str) -> List[str]:
        t = text.lower()
        syms: List[str] = []
        for sym, patterns in SYMBOL_PATTERNS.items():
            for pat in patterns:
                if re.search(pat, t):
                    syms.append(sym)
                    break
        return syms

    def dampen_for(self, symbol: str) -> Tuple[float, List[NewsEvent]]:
        """Return (dampen_factor, events) for a given symbol."""
        cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=3)
        recent = [e for e in self._cache if e.published_at >= cutoff and symbol in e.symbols]
        if not recent:
            return 1.0, []
        any_critical = any(e.severity >= 1.0 for e in recent)
        max_severity = max(e.severity for e in recent)
        if any_critical:
            return 0.1, recent
        dampen = max(0.1, min(1.0, 1.0 - max_severity + 0.1))
        return float(dampen), recent
