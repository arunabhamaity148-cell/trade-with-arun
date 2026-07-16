"""Institutional News Guard — structured event intelligence for signal dampening.

This module is intentionally self-contained in a single file. It never
produces trading signals and never touches private/authenticated endpoints.
Its role is restricted to event collection, event normalization, duplicate
collapse, lifecycle tracking, propagation-aware impact assessment, and
confidence / risk modifiers for the live signal engine.
"""
from __future__ import annotations

import asyncio
import csv
import hashlib
import math
import re
import time
from collections import OrderedDict, deque
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Deque, Dict, Iterable, List, Optional, Sequence, Set, Tuple

import feedparser
import httpx
from pydantic import BaseModel, Field
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from twa.config import Settings
from twa.logging import get_logger
from twa.models.types import NewsEvent

log = get_logger("news")

_MAX_EVENTS = 512
_MAX_EVIDENCE_PER_EVENT = 8
_MAX_DEDUP_CACHE = 2048
_DEFAULT_EVENT_TTL_S = 7 * 24 * 3600
_HEALTH_WINDOW_S = 900.0

_RSS_SOURCES: Dict[str, str] = {
    "coindesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "cointelegraph": "https://cointelegraph.com/rss",
    "bitcoinmagazine": "https://bitcoinmagazine.com/.rss/full/",
}
_CRYPTO_PANIC_URL = "https://cryptopanic.com/api/v1/posts/"
_FEAR_GREED_URL = "https://api.alternative.me/fng/"
_FRED_VIX_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=VIXCLS"
_STATUS_PAGES: Dict[str, str] = {
    "BINANCE": "https://www.binance.com/en/support/announcement",
    "BYBIT": "https://announcements.bybit.com/",
    "OKX": "https://www.okx.com/help/announcements",
    "HYPERLIQUID": "https://status.hyperliquid.xyz/",
    "DERIBIT": "https://status.deribit.com/",
}

_STOP_WORDS = {
    "a", "an", "and", "amid", "as", "at", "by", "for", "from", "in", "into", "is", "of", "on",
    "or", "the", "to", "with", "after", "before", "over", "under", "crypto", "market", "markets",
}

_ASSET_ALIASES: Dict[str, Tuple[str, ...]] = {
    "BTCUSDT": ("btc", "bitcoin", "bitcoin etf", "spot bitcoin"),
    "ETHUSDT": ("eth", "ethereum", "ether"),
    "SOLUSDT": ("sol", "solana"),
    "BNBUSDT": ("bnb", "binance coin"),
    "XRPUSDT": ("xrp", "ripple"),
    "ADAUSDT": ("ada", "cardano"),
    "DOGEUSDT": ("doge", "dogecoin"),
    "LINKUSDT": ("link", "chainlink"),
    "AVAXUSDT": ("avax", "avalanche"),
    "OPUSDT": ("op", "optimism"),
    "ARBUSDT": ("arb", "arbitrum"),
    "MATICUSDT": ("matic", "polygon"),
    "SUIUSDT": ("sui",),
    "JUPUSDT": ("jup", "jupiter"),
    "RAYUSDT": ("ray", "raydium"),
    "BONKUSDT": ("bonk",),
}

_ENTITY_ALIASES: Dict[str, Tuple[str, ...]] = {
    "BINANCE": ("binance",),
    "BYBIT": ("bybit",),
    "OKX": ("okx",),
    "DERIBIT": ("deribit",),
    "HYPERLIQUID": ("hyperliquid",),
    "SEC": ("sec", "securities and exchange commission"),
    "ETF": ("etf", "exchange traded fund"),
    "FED": ("fed", "federal reserve", "fomc", "powell"),
    "USDT": ("usdt", "tether"),
    "USDC": ("usdc", "circle"),
    "SOL_ECOSYSTEM": ("sol ecosystem", "solana ecosystem"),
    "ETH_ECOSYSTEM": ("ethereum ecosystem", "eth ecosystem", "layer 2"),
}

_NEGATIVE_KEYWORDS = {
    "hack", "hacked", "exploit", "breach", "stolen", "liquidation", "liquidations", "outage",
    "halt", "paused", "emergency", "investigation", "lawsuit", "fraud", "bankruptcy", "delisting",
    "depeg", "attack", "insolvency", "shutdown", "suspend", "suspension", "validator issue",
}
_POSITIVE_KEYWORDS = {
    "approval", "approved", "launch", "resume", "resumed", "listing", "partnership", "upgrade",
    "rate cut", "inflow", "adoption", "buyback", "integration",
}
_RESOLUTION_KEYWORDS = {
    "resolved", "restored", "all clear", "reopened", "back online", "issue fixed", "operational",
}


class EventCategory(str):
    MACRO = "macro"
    ETF = "etf"
    SEC = "sec"
    EXCHANGE = "exchange"
    HACK = "hack"
    EXPLOIT = "exploit"
    BRIDGE = "bridge"
    VALIDATOR = "validator"
    FORK = "fork"
    TOKEN_UNLOCK = "token_unlock"
    WHALE = "whale"
    STABLECOIN = "stablecoin"
    FUNDING = "funding"
    OPEN_INTEREST = "open_interest"
    LIQUIDATIONS = "liquidations"
    LISTING = "listing"
    DELISTING = "delisting"
    MAINTENANCE = "maintenance"
    CHAIN_HALT = "chain_halt"
    EMERGENCY = "emergency"
    GENERAL_MARKET = "general_market"


class EventLifecycle(str):
    DETECTED = "detected"
    CONFIRMED = "confirmed"
    ESCALATING = "escalating"
    PEAK = "peak"
    DECAY = "decay"
    RESOLVED = "resolved"
    EXPIRED = "expired"


class RawNewsItem(BaseModel):
    title: str
    source: str
    url: str
    published_at: datetime
    summary: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)


class EventEvidence(BaseModel):
    title: str
    source: str
    url: str
    published_at: datetime
    summary: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)


class EventRecord(BaseModel):
    id: str
    fingerprint: str
    category: str
    state: str
    title: str
    summary: str
    source_primary: str
    published_at: datetime
    first_seen_at: datetime
    last_seen_at: datetime
    peak_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    severity: float = 0.0
    confidence: float = 0.0
    sentiment: float = 0.0
    evidence_count: int = 1
    mention_count: int = 1
    entities: List[str] = Field(default_factory=list)
    affected_nodes: List[str] = Field(default_factory=list)
    affected_symbols: List[str] = Field(default_factory=list)
    evidence: List[EventEvidence] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ImpactAssessment(BaseModel):
    symbol: str
    confidence_multiplier: float = 1.0
    risk_multiplier: float = 1.0
    regime_modifier: float = 0.0
    signal_suppressed: bool = False
    signal_cancelled: bool = False
    signal_delay_s: int = 0
    confidence_score: float = 0.0
    contributing_event_ids: List[str] = Field(default_factory=list)
    reasons: List[str] = Field(default_factory=list)


class RollingHealth:
    def __init__(self) -> None:
        self.last_ok_ts: Optional[float] = None
        self.last_error: Optional[str] = None
        self._events: Deque[Tuple[float, bool]] = deque(maxlen=512)

    def record_success(self) -> None:
        now = time.time()
        self.last_ok_ts = now
        self._events.append((now, True))
        self._prune(now)

    def record_error(self, error: str) -> None:
        now = time.time()
        self.last_error = error
        self._events.append((now, False))
        self._prune(now)

    def health(self) -> Dict[str, Any]:
        now = time.time()
        self._prune(now)
        errors = sum(1 for _, ok in self._events if not ok)
        successes = sum(1 for _, ok in self._events if ok)
        total = errors + successes
        return {
            "exchange": "news_guard",
            "last_ok_ts": self.last_ok_ts,
            "last_error": self.last_error,
            "recent_error_count": errors,
            "recent_success_count": successes,
            "recent_error_rate": float(errors / total) if total else 0.0,
            "recent_window_s": _HEALTH_WINDOW_S,
        }

    def _prune(self, now: float) -> None:
        while self._events and (now - self._events[0][0]) > _HEALTH_WINDOW_S:
            self._events.popleft()


class EntityExtractor:
    def extract(self, text: str) -> Tuple[List[str], List[str]]:
        clean = _normalise_text(text)
        symbols: List[str] = []
        entities: List[str] = []
        for symbol, aliases in _ASSET_ALIASES.items():
            if any(_contains_phrase(clean, alias) for alias in aliases):
                symbols.append(symbol)
        for entity, aliases in _ENTITY_ALIASES.items():
            if any(_contains_phrase(clean, alias) for alias in aliases):
                entities.append(entity)
        if any(sym.startswith("SOL") or sym in {"JUPUSDT", "RAYUSDT", "BONKUSDT"} for sym in symbols):
            entities.append("SOL_ECOSYSTEM")
        if any(sym in {"ETHUSDT", "ARBUSDT", "OPUSDT", "MATICUSDT"} for sym in symbols):
            entities.append("ETH_ECOSYSTEM")
        return sorted(set(symbols)), sorted(set(entities))


class EventNormalizer:
    _category_rules: Sequence[Tuple[str, Tuple[str, ...]]] = (
        (EventCategory.EMERGENCY, ("emergency", "urgent", "critical incident")),
        (EventCategory.CHAIN_HALT, ("chain halt", "block production halted", "halted block", "network halt", "finality issue", "finality issues")),
        (EventCategory.MAINTENANCE, ("maintenance", "scheduled upgrade", "withdrawals paused", "withdrawal pause", "withdrawals halt", "deposits paused", "wallet outage", "outage")),
        (EventCategory.DELISTING, ("delisting", "delist", "removed from listing")),
        (EventCategory.LISTING, ("listing", "listed", "goes live", "trading opens")),
        (EventCategory.HACK, ("hack", "hacked", "breach", "stolen")),
        (EventCategory.EXPLOIT, ("exploit", "drained", "smart contract exploit")),
        (EventCategory.BRIDGE, ("bridge", "cross-chain bridge")),
        (EventCategory.VALIDATOR, ("validator", "validators", "slashing", "missed attestations", "miss blocks")),
        (EventCategory.FORK, ("hard fork", "soft fork", "fork activation")),
        (EventCategory.TOKEN_UNLOCK, ("token unlock", "vesting unlock", "cliff unlock")),
        (EventCategory.STABLECOIN, ("depeg", "stablecoin", "redemption", "peg restored")),
        (EventCategory.WHALE, ("whale", "large transfer", "moved to exchange")),
        (EventCategory.FUNDING, ("funding rate", "positive funding", "negative funding")),
        (EventCategory.OPEN_INTEREST, ("open interest", "oi spike", "oi flush")),
        (EventCategory.LIQUIDATIONS, ("liquidation", "liquidations", "long squeeze", "short squeeze")),
        (EventCategory.SEC, (" sec ", "securities and exchange commission", "lawsuit", "subpoena")),
        (EventCategory.ETF, ("etf", "exchange traded fund", "spot bitcoin")),
        (EventCategory.MACRO, ("cpi", "pce", "payrolls", "fomc", "federal reserve", "rate hike", "rate cut")),
        (EventCategory.EXCHANGE, ("exchange", "matching engine", "trading venue", "orderbook")),
    )
    _base_severity: Dict[str, float] = {
        EventCategory.EMERGENCY: 0.98,
        EventCategory.CHAIN_HALT: 0.95,
        EventCategory.HACK: 0.95,
        EventCategory.EXPLOIT: 0.92,
        EventCategory.MAINTENANCE: 0.72,
        EventCategory.DELISTING: 0.82,
        EventCategory.LISTING: 0.40,
        EventCategory.SEC: 0.82,
        EventCategory.ETF: 0.58,
        EventCategory.MACRO: 0.70,
        EventCategory.STABLECOIN: 0.86,
        EventCategory.LIQUIDATIONS: 0.74,
        EventCategory.WHALE: 0.46,
        EventCategory.TOKEN_UNLOCK: 0.55,
        EventCategory.FUNDING: 0.42,
        EventCategory.OPEN_INTEREST: 0.45,
        EventCategory.VALIDATOR: 0.66,
        EventCategory.FORK: 0.60,
        EventCategory.BRIDGE: 0.76,
        EventCategory.EXCHANGE: 0.62,
        EventCategory.GENERAL_MARKET: 0.38,
    }

    def __init__(self) -> None:
        self.entities = EntityExtractor()

    def normalize(self, item: RawNewsItem, now: Optional[datetime] = None) -> EventRecord:
        ts_now = now or _utcnow()
        title = item.title.strip()[:300]
        summary = item.summary.strip()[:800]
        merged = _normalise_text(f"{title} {summary}")
        symbols, entities = self.entities.extract(merged)
        category = self._categorize(merged)
        severity = self._severity(merged, category)
        sentiment = self._sentiment(merged, category)
        confidence = self._initial_confidence(item.source, symbols, entities, category)
        affected_nodes = sorted(set(symbols + entities))
        if category == EventCategory.STABLECOIN and not affected_nodes:
            affected_nodes = ["USDT"]
        if category in {EventCategory.MACRO, EventCategory.SEC, EventCategory.ETF} and "BTCUSDT" not in affected_nodes:
            affected_nodes.append("BTCUSDT")
        resolved_at = item.published_at if self._is_resolution(merged) else None
        fingerprint = self._fingerprint(category, merged, symbols, entities)
        event_id = hashlib.sha1(f"{fingerprint}|{item.url}".encode()).hexdigest()[:16]
        evidence = EventEvidence(
            title=title,
            source=item.source,
            url=item.url,
            published_at=_ensure_utc(item.published_at),
            summary=summary,
            metadata=dict(item.metadata),
        )
        return EventRecord(
            id=event_id,
            fingerprint=fingerprint,
            category=category,
            state=EventLifecycle.RESOLVED if resolved_at else EventLifecycle.DETECTED,
            title=title,
            summary=summary,
            source_primary=item.source,
            published_at=_ensure_utc(item.published_at),
            first_seen_at=ts_now,
            last_seen_at=ts_now,
            resolved_at=resolved_at,
            severity=severity,
            confidence=confidence,
            sentiment=sentiment,
            evidence_count=1,
            mention_count=1,
            entities=entities,
            affected_nodes=affected_nodes,
            affected_symbols=symbols,
            evidence=[evidence],
            metadata=dict(item.metadata),
        )

    def _categorize(self, text: str) -> str:
        padded = f" {text} "
        for category, keywords in self._category_rules:
            if any(keyword in padded for keyword in keywords):
                return category
        return EventCategory.GENERAL_MARKET

    def _severity(self, text: str, category: str) -> float:
        severity = self._base_severity.get(category, 0.35)
        if any(k in text for k in ("critical", "major", "massive", "urgent", "$100m", "$1b")):
            severity += 0.12
        if any(k in text for k in ("rumor", "reportedly", "unconfirmed", "speculation")):
            severity -= 0.08
        if any(k in text for k in _RESOLUTION_KEYWORDS):
            severity -= 0.18
        return float(min(0.99, max(0.10, severity)))

    def _sentiment(self, text: str, category: str) -> float:
        negative = sum(1 for k in _NEGATIVE_KEYWORDS if k in text)
        positive = sum(1 for k in _POSITIVE_KEYWORDS if k in text)
        base = 0.0
        if category in {EventCategory.HACK, EventCategory.EXPLOIT, EventCategory.CHAIN_HALT,
                        EventCategory.EMERGENCY, EventCategory.DELISTING, EventCategory.SEC,
                        EventCategory.STABLECOIN, EventCategory.LIQUIDATIONS}:
            base -= 0.35
        if category in {EventCategory.ETF, EventCategory.LISTING}:
            base += 0.18
        score = base + 0.14 * positive - 0.16 * negative
        return float(max(-1.0, min(1.0, score)))

    def _initial_confidence(self, source: str, symbols: List[str], entities: List[str], category: str) -> float:
        credibility = 0.56
        src = source.lower()
        if any(name in src for name in ("coindesk", "cointelegraph", "bitcoinmagazine", "cryptopanic")):
            credibility += 0.08
        if any(name in src for name in ("status", "binance", "bybit", "okx", "deribit", "hyperliquid")):
            credibility += 0.10
        if symbols:
            credibility += 0.06
        if entities:
            credibility += 0.04
        if category == EventCategory.GENERAL_MARKET:
            credibility -= 0.05
        return float(min(0.95, max(0.30, credibility)))

    def _is_resolution(self, text: str) -> bool:
        return any(keyword in text for keyword in _RESOLUTION_KEYWORDS)

    def _fingerprint(self, category: str, text: str, symbols: List[str], entities: List[str]) -> str:
        tokens = [tok for tok in _tokenise(text) if tok not in _STOP_WORDS][:20]
        signature = "|".join([category, ",".join(symbols[:4]), ",".join(entities[:4]), " ".join(tokens)])
        return hashlib.sha1(signature.encode()).hexdigest()[:20]


class DuplicateDetector:
    def find_match(self, candidate: EventRecord, events: Iterable[EventRecord]) -> Optional[str]:
        for existing in events:
            if existing.urls_match(candidate):
                return existing.id
            if not self._compatible_categories(candidate.category, existing.category):
                continue
            age_gap = abs((candidate.published_at - existing.published_at).total_seconds())
            if age_gap > 36 * 3600:
                continue
            sim = self.similarity(candidate, existing)
            if sim >= 0.80:
                return existing.id
            if sim >= 0.65 and self._entity_overlap(candidate, existing):
                return existing.id
            if self._entity_overlap(candidate, existing) and self._token_overlap(candidate, existing) >= 2:
                return existing.id
        return None

    def similarity(self, left: EventRecord, right: EventRecord) -> float:
        left_tokens = set(_shingles(_normalise_text(f"{left.title} {left.summary}"), 3))
        right_tokens = set(_shingles(_normalise_text(f"{right.title} {right.summary}"), 3))
        if not left_tokens or not right_tokens:
            return 0.0
        jaccard = len(left_tokens & right_tokens) / max(1, len(left_tokens | right_tokens))
        entity_bonus = 0.15 if self._entity_overlap(left, right) else 0.0
        symbol_bonus = 0.10 if set(left.affected_symbols) & set(right.affected_symbols) else 0.0
        return float(min(1.0, jaccard + entity_bonus + symbol_bonus))

    def _compatible_categories(self, left: str, right: str) -> bool:
        if left == right:
            return True
        operational = {EventCategory.VALIDATOR, EventCategory.CHAIN_HALT, EventCategory.MAINTENANCE, EventCategory.EXCHANGE}
        return left in operational and right in operational

    def _entity_overlap(self, left: EventRecord, right: EventRecord) -> bool:
        return bool(set(left.entities) & set(right.entities) or set(left.affected_symbols) & set(right.affected_symbols))

    def _token_overlap(self, left: EventRecord, right: EventRecord) -> int:
        left_tokens = {tok for tok in _tokenise(_normalise_text(f"{left.title} {left.summary}")) if tok not in _STOP_WORDS}
        right_tokens = {tok for tok in _tokenise(_normalise_text(f"{right.title} {right.summary}")) if tok not in _STOP_WORDS}
        return len(left_tokens & right_tokens)


class EventGraph:
    def __init__(self) -> None:
        self.edges: Dict[str, Dict[str, float]] = {}
        self._bootstrap()

    def add_edge(self, source: str, target: str, weight: float) -> None:
        self.edges.setdefault(source, {})[target] = float(max(0.0, min(1.0, weight)))

    def impact_weights(self, seeds: Sequence[str], *, max_hops: int = 3, hop_decay: float = 0.72) -> Dict[str, float]:
        out: Dict[str, float] = {}
        frontier: List[Tuple[str, float, int]] = [(seed, 1.0, 0) for seed in seeds]
        while frontier:
            node, weight, hops = frontier.pop(0)
            if weight <= out.get(node, 0.0):
                continue
            out[node] = weight
            if hops >= max_hops:
                continue
            for nxt, edge_weight in self.edges.get(node, {}).items():
                nxt_weight = weight * edge_weight * hop_decay
                if nxt_weight < 0.05:
                    continue
                frontier.append((nxt, nxt_weight, hops + 1))
        return out

    def _bootstrap(self) -> None:
        self.add_edge("BTCUSDT", "ETHUSDT", 0.78)
        self.add_edge("BTCUSDT", "SOLUSDT", 0.58)
        self.add_edge("ETHUSDT", "ARBUSDT", 0.88)
        self.add_edge("ETHUSDT", "OPUSDT", 0.84)
        self.add_edge("ETHUSDT", "MATICUSDT", 0.76)
        self.add_edge("SOLUSDT", "JUPUSDT", 0.88)
        self.add_edge("SOLUSDT", "RAYUSDT", 0.82)
        self.add_edge("SOLUSDT", "BONKUSDT", 0.78)
        self.add_edge("SOL_ECOSYSTEM", "SOLUSDT", 0.95)
        self.add_edge("ETH_ECOSYSTEM", "ETHUSDT", 0.95)
        self.add_edge("BINANCE", "BNBUSDT", 0.98)
        self.add_edge("BINANCE", "BTCUSDT", 0.64)
        self.add_edge("BINANCE", "ETHUSDT", 0.60)
        self.add_edge("BYBIT", "BTCUSDT", 0.58)
        self.add_edge("BYBIT", "ETHUSDT", 0.52)
        self.add_edge("OKX", "BTCUSDT", 0.50)
        self.add_edge("DERIBIT", "BTCUSDT", 0.70)
        self.add_edge("DERIBIT", "ETHUSDT", 0.64)
        self.add_edge("HYPERLIQUID", "BTCUSDT", 0.44)
        self.add_edge("HYPERLIQUID", "ETHUSDT", 0.40)
        self.add_edge("SEC", "BTCUSDT", 0.70)
        self.add_edge("ETF", "BTCUSDT", 0.85)
        self.add_edge("FED", "BTCUSDT", 0.62)
        self.add_edge("FED", "ETHUSDT", 0.54)
        self.add_edge("USDT", "BTCUSDT", 0.80)
        self.add_edge("USDT", "ETHUSDT", 0.72)


class TimeDecayEngine:
    HALF_LIFE_S: Dict[str, float] = {
        EventCategory.EMERGENCY: 2 * 3600.0,
        EventCategory.CHAIN_HALT: 3 * 3600.0,
        EventCategory.MAINTENANCE: 4 * 3600.0,
        EventCategory.HACK: 10 * 3600.0,
        EventCategory.EXPLOIT: 10 * 3600.0,
        EventCategory.LIQUIDATIONS: 6 * 3600.0,
        EventCategory.FUNDING: 5 * 3600.0,
        EventCategory.OPEN_INTEREST: 5 * 3600.0,
        EventCategory.WHALE: 6 * 3600.0,
        EventCategory.TOKEN_UNLOCK: 12 * 3600.0,
        EventCategory.STABLECOIN: 16 * 3600.0,
        EventCategory.EXCHANGE: 8 * 3600.0,
        EventCategory.DELISTING: 20 * 3600.0,
        EventCategory.LISTING: 12 * 3600.0,
        EventCategory.SEC: 72 * 3600.0,
        EventCategory.ETF: 48 * 3600.0,
        EventCategory.MACRO: 36 * 3600.0,
        EventCategory.VALIDATOR: 12 * 3600.0,
        EventCategory.FORK: 18 * 3600.0,
        EventCategory.BRIDGE: 18 * 3600.0,
        EventCategory.GENERAL_MARKET: 10 * 3600.0,
    }
    STATE_MULTIPLIER: Dict[str, float] = {
        EventLifecycle.DETECTED: 0.85,
        EventLifecycle.CONFIRMED: 0.95,
        EventLifecycle.ESCALATING: 1.05,
        EventLifecycle.PEAK: 1.10,
        EventLifecycle.DECAY: 0.60,
        EventLifecycle.RESOLVED: 0.35,
        EventLifecycle.EXPIRED: 0.0,
    }

    def half_life(self, category: str) -> float:
        return self.HALF_LIFE_S.get(category, 10 * 3600.0)

    def decay(self, event: EventRecord, now: Optional[datetime] = None) -> float:
        ts_now = now or _utcnow()
        ref = event.resolved_at or event.last_seen_at or event.first_seen_at
        age_s = max(0.0, (ts_now - ref).total_seconds())
        half_life = self.half_life(event.category)
        if event.resolved_at is not None:
            half_life *= 0.65
        raw = math.exp(-math.log(2.0) * age_s / max(1.0, half_life))
        return float(max(0.0, min(1.0, raw * self.STATE_MULTIPLIER.get(event.state, 1.0))))


class ConfidenceEngine:
    def score(self, event: EventRecord) -> float:
        sources = {ev.source.lower() for ev in event.evidence}
        diversity = min(0.18, 0.06 * max(0, len(sources) - 1))
        mentions = min(0.15, 0.03 * max(0, event.mention_count - 1))
        specificity = 0.05 if event.affected_symbols else 0.0
        category_bonus = 0.04 if event.category != EventCategory.GENERAL_MARKET else -0.02
        return float(min(0.99, max(0.25, event.confidence + diversity + mentions + specificity + category_bonus)))


class EventMemory:
    def __init__(
        self,
        *,
        max_events: int = _MAX_EVENTS,
        ttl_s: int = _DEFAULT_EVENT_TTL_S,
        max_evidence_per_event: int = _MAX_EVIDENCE_PER_EVENT,
        decay_engine: Optional[TimeDecayEngine] = None,
        confidence_engine: Optional[ConfidenceEngine] = None,
    ) -> None:
        self.max_events = max_events
        self.ttl_s = ttl_s
        self.max_evidence_per_event = max_evidence_per_event
        self.decay_engine = decay_engine or TimeDecayEngine()
        self.confidence_engine = confidence_engine or ConfidenceEngine()
        self.events: "OrderedDict[str, EventRecord]" = OrderedDict()
        self.dedup_cache: Deque[str] = deque(maxlen=_MAX_DEDUP_CACHE)

    def upsert(self, event: EventRecord, matcher: DuplicateDetector, now: Optional[datetime] = None) -> EventRecord:
        ts_now = now or _utcnow()
        match_id = matcher.find_match(event, self.events.values())
        if match_id and match_id in self.events:
            merged = self._merge(self.events[match_id], event, ts_now)
            self.events[match_id] = merged
            self.events.move_to_end(match_id)
            self.prune(ts_now)
            return merged
        self._transition(event, ts_now)
        self.events[event.id] = event
        self.events.move_to_end(event.id)
        self.dedup_cache.append(event.fingerprint)
        self.prune(ts_now)
        return event

    def active_events(self, now: Optional[datetime] = None) -> List[EventRecord]:
        ts_now = now or _utcnow()
        self.prune(ts_now)
        out: List[EventRecord] = []
        for event in list(self.events.values()):
            self._transition(event, ts_now)
            if event.state != EventLifecycle.EXPIRED:
                out.append(event)
        return out

    def prune(self, now: Optional[datetime] = None) -> None:
        ts_now = now or _utcnow()
        expired: List[str] = []
        for event_id, event in list(self.events.items()):
            self._transition(event, ts_now)
            too_old = (ts_now - event.first_seen_at).total_seconds() > self.ttl_s
            if too_old or event.state == EventLifecycle.EXPIRED:
                expired.append(event_id)
        for event_id in expired:
            self.events.pop(event_id, None)
        while len(self.events) > self.max_events:
            self.events.popitem(last=False)

    def _merge(self, base: EventRecord, incoming: EventRecord, now: datetime) -> EventRecord:
        base.last_seen_at = now
        base.published_at = min(base.published_at, incoming.published_at)
        base.severity = max(base.severity, incoming.severity)
        base.sentiment = float(max(-1.0, min(1.0, (base.sentiment + incoming.sentiment) / 2.0)))
        base.mention_count += 1
        base.evidence_count += 1
        base.entities = sorted(set(base.entities + incoming.entities))
        base.affected_nodes = sorted(set(base.affected_nodes + incoming.affected_nodes))
        base.affected_symbols = sorted(set(base.affected_symbols + incoming.affected_symbols))
        base.metadata.update(incoming.metadata)
        if incoming.resolved_at and (base.resolved_at is None or incoming.resolved_at > base.resolved_at):
            base.resolved_at = incoming.resolved_at
        for evidence in incoming.evidence:
            if evidence.url and any(ev.url == evidence.url for ev in base.evidence):
                continue
            base.evidence.append(evidence)
        base.evidence = base.evidence[-self.max_evidence_per_event :]
        if base.evidence_count >= 4 and base.peak_at is None:
            base.peak_at = now
        base.confidence = self.confidence_engine.score(base)
        self._transition(base, now)
        return base

    def _transition(self, event: EventRecord, now: datetime) -> None:
        age_s = max(0.0, (now - event.first_seen_at).total_seconds())
        half_life = self.decay_engine.half_life(event.category)
        if event.resolved_at is not None:
            resolved_age = max(0.0, (now - event.resolved_at).total_seconds())
            event.state = EventLifecycle.RESOLVED if resolved_age <= half_life else EventLifecycle.EXPIRED
            return
        if age_s > half_life * 4.0:
            event.state = EventLifecycle.EXPIRED
            return
        if event.evidence_count >= 5:
            event.state = EventLifecycle.PEAK
            event.peak_at = event.peak_at or now
        elif event.evidence_count >= 3:
            event.state = EventLifecycle.ESCALATING
        elif event.evidence_count >= 2:
            event.state = EventLifecycle.CONFIRMED
        else:
            event.state = EventLifecycle.DETECTED
        if age_s > half_life * 1.5:
            event.state = EventLifecycle.DECAY


class ImpactEngine:
    _critical_categories = {
        EventCategory.EMERGENCY,
        EventCategory.CHAIN_HALT,
        EventCategory.HACK,
        EventCategory.EXPLOIT,
        EventCategory.STABLECOIN,
    }

    def __init__(self, graph: Optional[EventGraph] = None, decay_engine: Optional[TimeDecayEngine] = None) -> None:
        self.graph = graph or EventGraph()
        self.decay_engine = decay_engine or TimeDecayEngine()

    def assess(self, symbol: str, events: Sequence[EventRecord], now: Optional[datetime] = None) -> ImpactAssessment:
        ts_now = now or _utcnow()
        aggregate = 0.0
        strongest = 0.0
        reasons: List[str] = []
        contributing: List[str] = []
        for event in events:
            nodes = event.affected_nodes or event.affected_symbols or [symbol]
            weights = self.graph.impact_weights(nodes)
            asset_weight = weights.get(symbol, 0.0)
            if asset_weight <= 0.0:
                continue
            decay = self.decay_engine.decay(event, ts_now)
            directional_risk = 1.15 if event.sentiment < 0 else 0.35
            contribution = float(min(0.98, event.severity * event.confidence * asset_weight * decay * directional_risk))
            if contribution <= 0.0:
                continue
            contributing.append(event.id)
            aggregate = 1.0 - ((1.0 - aggregate) * (1.0 - contribution))
            strongest = max(strongest, contribution)
            reasons.append(f"{event.category}:{event.title[:90]}")
        if not contributing:
            return ImpactAssessment(symbol=symbol)
        confidence_multiplier = float(max(0.10, 1.0 - aggregate))
        risk_multiplier = float(1.0 + strongest + aggregate * 0.5)
        regime_modifier = float(-min(0.50, aggregate * 0.75))
        signal_suppressed = aggregate >= 0.55
        signal_cancelled = any(
            event.category in self._critical_categories and self.decay_engine.decay(event, ts_now) > 0.45
            for event in events
            if event.id in contributing and symbol in self.graph.impact_weights(event.affected_nodes or event.affected_symbols)
        )
        signal_delay_s = int(min(3600, round(aggregate * 1800)))
        return ImpactAssessment(
            symbol=symbol,
            confidence_multiplier=confidence_multiplier,
            risk_multiplier=risk_multiplier,
            regime_modifier=regime_modifier,
            signal_suppressed=signal_suppressed,
            signal_cancelled=signal_cancelled,
            signal_delay_s=signal_delay_s,
            confidence_score=float(aggregate),
            contributing_event_ids=contributing,
            reasons=reasons[:6],
        )


class TelegramFormatter:
    def format_events(self, symbol: str, assessment: ImpactAssessment, events: Sequence[EventRecord]) -> List[str]:
        lines = [
            f"{symbol}: news guard confidence×{assessment.confidence_multiplier:.2f}",
            f"risk×{assessment.risk_multiplier:.2f}, delay={assessment.signal_delay_s}s",
        ]
        for event in events[:3]:
            lines.append(f"- {event.category}/{event.state}: {event.title}")
        return lines


class EventCollector:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def collect(self) -> List[RawNewsItem]:
        tasks = [self._fetch_rss()]
        if self.settings.cryptopanic_public_key:
            tasks.append(self._fetch_cryptopanic())
        tasks.extend([
            self._fetch_fear_greed(),
            self._fetch_fred_vix(),
            self._fetch_status_pages(),
        ])
        results = await asyncio.gather(*tasks, return_exceptions=True)
        items: List[RawNewsItem] = []
        for result in results:
            if isinstance(result, Exception):
                log.warning("news.collector.task_failed", err=str(result))
                continue
            items.extend(result)
        return items

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=3.0),
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
    )
    async def _get_text(self, url: str, *, params: Optional[Dict[str, Any]] = None) -> str:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            return resp.text

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=3.0),
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
    )
    async def _get_json(self, url: str, *, params: Optional[Dict[str, Any]] = None) -> Any:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            return resp.json()

    async def _fetch_rss(self) -> List[RawNewsItem]:
        items: List[RawNewsItem] = []
        for source, url in _RSS_SOURCES.items():
            try:
                text = await self._get_text(url)
                feed = feedparser.parse(text)
                for entry in feed.entries[:30]:
                    items.append(
                        RawNewsItem(
                            title=str(entry.get("title", ""))[:300],
                            source=source,
                            url=str(entry.get("link", "")),
                            published_at=_parse_dt(entry.get("published") or entry.get("updated")) or _utcnow(),
                            summary=_strip_html(str(entry.get("summary", "") or entry.get("description", "")))[:800],
                        )
                    )
            except Exception as exc:  # noqa: BLE001
                log.warning("news.rss.fetch_failed", source=source, url=url, err=str(exc))
        return items

    async def _fetch_cryptopanic(self) -> List[RawNewsItem]:
        params: Dict[str, Any] = {"public": "true", "kind": "news"}
        if self.settings.cryptopanic_public_key:
            params["auth_token"] = self.settings.cryptopanic_public_key
        try:
            payload = await self._get_json(_CRYPTO_PANIC_URL, params=params)
        except Exception as exc:  # noqa: BLE001
            log.warning("news.cryptopanic.fetch_failed", err=str(exc))
            return []
        items: List[RawNewsItem] = []
        for row in payload.get("results", [])[:30]:
            currencies = [str(x.get("code", "")).upper() for x in (row.get("currencies") or []) if x.get("code")]
            items.append(
                RawNewsItem(
                    title=str(row.get("title", ""))[:300],
                    source="cryptopanic",
                    url=str(row.get("url", "")),
                    published_at=_parse_dt(row.get("published_at")) or _utcnow(),
                    summary=str(row.get("slug", ""))[:800],
                    metadata={"currencies": currencies},
                )
            )
        return items

    async def _fetch_fear_greed(self) -> List[RawNewsItem]:
        try:
            payload = await self._get_json(_FEAR_GREED_URL, params={"limit": 1, "format": "json"})
            row = (payload.get("data") or [{}])[0]
            value = int(row.get("value", 50))
        except Exception as exc:  # noqa: BLE001
            log.warning("news.fear_greed.fetch_failed", err=str(exc))
            return []
        if 35 <= value <= 65:
            return []
        mood = "extreme fear" if value < 25 else ("fear" if value < 35 else ("greed" if value > 65 else "extreme greed"))
        title = f"Alternative.me sentiment index shows {mood} ({value})"
        return [
            RawNewsItem(
                title=title,
                source="alternative.me",
                url="https://alternative.me/crypto/fear-and-greed-index/",
                published_at=_utcnow(),
                summary=title,
                metadata={"fear_greed": value},
            )
        ]

    async def _fetch_fred_vix(self) -> List[RawNewsItem]:
        try:
            text = await self._get_text(_FRED_VIX_URL)
            rows = list(csv.DictReader(text.splitlines()))
            values = [float(r["VIXCLS"]) for r in rows if r.get("VIXCLS") not in {None, "."}]
        except Exception as exc:  # noqa: BLE001
            log.warning("news.fred.fetch_failed", err=str(exc))
            return []
        if len(values) < 20:
            return []
        recent = values[-1]
        trailing = values[-20:]
        mean = sum(trailing) / len(trailing)
        var = sum((x - mean) ** 2 for x in trailing) / len(trailing)
        std = math.sqrt(var)
        if recent < mean + std:
            return []
        title = f"VIX macro stress elevated at {recent:.2f} versus 20-day mean {mean:.2f}"
        return [
            RawNewsItem(
                title=title,
                source="fred",
                url="https://fred.stlouisfed.org/series/VIXCLS",
                published_at=_utcnow(),
                summary=title,
            )
        ]

    async def _fetch_status_pages(self) -> List[RawNewsItem]:
        items: List[RawNewsItem] = []
        for exchange, url in _STATUS_PAGES.items():
            try:
                text = _normalise_text(await self._get_text(url))
            except Exception as exc:  # noqa: BLE001
                log.warning("news.status.fetch_failed", exchange=exchange, url=url, err=str(exc))
                continue
            match = re.search(
                r"(incident|outage|maintenance|degraded|withdrawals paused|deposits paused|network issue|resolved)",
                text,
            )
            if not match:
                continue
            snippet = text[max(0, match.start() - 50) : match.start() + 180]
            title = f"{exchange} status update: {snippet.strip()}"
            items.append(
                RawNewsItem(
                    title=title[:300],
                    source=f"{exchange.lower()}_status",
                    url=url,
                    published_at=_utcnow(),
                    summary=snippet[:800],
                    metadata={"exchange": exchange},
                )
            )
        return items


class NewsGuard:
    """Public entry point for event intelligence.

    External compatibility is preserved:
      * `refresh()` remains async.
      * `dampen_for(symbol)` still returns `(confidence_multiplier, surface_events)`.

    Richer behaviour is available through `assess(symbol)` for callers that want
    suppression / cancellation / delay / regime modifiers in addition to the
    backward-compatible dampening factor.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self.collector = EventCollector(settings)
        self.normalizer = EventNormalizer()
        self.matcher = DuplicateDetector()
        self.graph = EventGraph()
        self.decay = TimeDecayEngine()
        self.memory = EventMemory(decay_engine=self.decay)
        self.impact = ImpactEngine(self.graph, self.decay)
        self.formatter = TelegramFormatter()
        self.health_tracker = RollingHealth()
        self._last_fetch: float = 0.0

    async def refresh(self) -> None:
        if not self.settings.news_enabled:
            return
        if time.time() - self._last_fetch < self.settings.news_refresh_s:
            return
        self._last_fetch = time.time()
        try:
            items = await self.collector.collect()
            await self.ingest(items)
            self.health_tracker.record_success()
            log.debug("news.refresh", fetched=len(items), active=len(self.memory.events))
        except Exception as exc:  # noqa: BLE001
            self.health_tracker.record_error(str(exc))
            log.warning("news.refresh_failed", err=str(exc))

    async def ingest(self, items: Sequence[RawNewsItem]) -> None:
        now = _utcnow()
        for item in items:
            try:
                event = self.normalizer.normalize(item, now=now)
                self.memory.upsert(event, self.matcher, now=now)
            except Exception as exc:  # noqa: BLE001
                log.warning("news.ingest_failed", source=item.source, url=item.url, err=str(exc))
        self.memory.prune(now)

    def assess(self, symbol: str, now: Optional[datetime] = None) -> ImpactAssessment:
        active = self.memory.active_events(now)
        return self.impact.assess(symbol, active, now=now)

    def dampen_for(self, symbol: str) -> Tuple[float, List[NewsEvent]]:
        now = _utcnow()
        active = self.memory.active_events(now)
        relevant = []
        weights_by_id: Dict[str, float] = {}
        for event in active:
            weight = self.graph.impact_weights(event.affected_nodes or event.affected_symbols).get(symbol, 0.0)
            if weight <= 0.0:
                continue
            relevant.append(event)
            weights_by_id[event.id] = weight * self.decay.decay(event, now)
        relevant.sort(key=lambda event: weights_by_id.get(event.id, 0.0), reverse=True)
        assessment = self.impact.assess(symbol, relevant, now=now)
        return assessment.confidence_multiplier, [self._surface_event(event) for event in relevant[:8]]

    def health(self) -> Dict[str, Any]:
        doc = self.health_tracker.health()
        doc.update(
            {
                "cached_event_count": len(self.memory.events),
                "last_fetch_ts": self._last_fetch,
                "state_counts": self._state_counts(),
            }
        )
        return doc

    def _state_counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for event in self.memory.events.values():
            counts[event.state] = counts.get(event.state, 0) + 1
        return counts

    def _surface_event(self, event: EventRecord) -> NewsEvent:
        return NewsEvent(
            title=event.title,
            source=event.source_primary,
            url=event.evidence[-1].url if event.evidence else "",
            published_at=event.published_at,
            symbols=list(event.affected_symbols),
            severity=float(event.severity),
            sentiment=float(event.sentiment),
            category=f"{event.category}:{event.state}",
        )


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_dt(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return _ensure_utc(value)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    try:
        return _ensure_utc(datetime.fromisoformat(text.replace("Z", "+00:00")))
    except ValueError:
        pass
    try:
        return _ensure_utc(parsedate_to_datetime(text))
    except Exception:
        return None


def _strip_html(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text or "")).strip()


def _normalise_text(text: str) -> str:
    lowered = _strip_html(text).lower()
    lowered = re.sub(r"https?://\S+", " ", lowered)
    lowered = re.sub(r"[^a-z0-9$\.\-\s]", " ", lowered)
    lowered = re.sub(r"\s+", " ", lowered)
    return lowered.strip()


def _contains_phrase(text: str, phrase: str) -> bool:
    pattern = rf"(?<![a-z0-9]){re.escape(phrase.lower())}(?![a-z0-9])"
    return re.search(pattern, text) is not None


def _tokenise(text: str) -> List[str]:
    return [tok for tok in re.split(r"\s+", text) if tok]


def _shingles(text: str, size: int) -> List[str]:
    tokens = _tokenise(text)
    if len(tokens) <= size:
        return [" ".join(tokens)] if tokens else []
    return [" ".join(tokens[idx : idx + size]) for idx in range(len(tokens) - size + 1)]


def _event_urls_match(left: EventRecord, right: EventRecord) -> bool:
    left_urls = {ev.url for ev in left.evidence if ev.url}
    right_urls = {ev.url for ev in right.evidence if ev.url}
    return bool(left_urls & right_urls)


def _attach_url_match() -> None:
    def urls_match(self: EventRecord, other: EventRecord) -> bool:
        return _event_urls_match(self, other)

    setattr(EventRecord, "urls_match", urls_match)


_attach_url_match()

__all__ = [
    "DuplicateDetector",
    "EntityExtractor",
    "EventCategory",
    "EventGraph",
    "EventLifecycle",
    "EventMemory",
    "EventNormalizer",
    "EventRecord",
    "ImpactAssessment",
    "ImpactEngine",
    "NewsGuard",
    "RawNewsItem",
    "TelegramFormatter",
    "TimeDecayEngine",
]
