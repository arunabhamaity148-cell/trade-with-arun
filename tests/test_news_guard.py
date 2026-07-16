"""Institutional news guard tests."""
from datetime import timedelta, timezone

from twa.config import Settings
from twa.news.guard import (
    DuplicateDetector,
    EventCategory,
    EventGraph,
    EventLifecycle,
    EventMemory,
    EventNormalizer,
    ImpactEngine,
    NewsGuard,
    RawNewsItem,
    TimeDecayEngine,
)


def _item(title: str, *, source: str = "coindesk", summary: str = "") -> RawNewsItem:
    from datetime import datetime

    return RawNewsItem(
        title=title,
        source=source,
        url=f"https://example.com/{abs(hash((title, source))) % 10_000}",
        published_at=datetime.now(tz=timezone.utc),
        summary=summary,
    )


def test_event_normalization_extracts_category_and_symbol():
    normalizer = EventNormalizer()
    event = normalizer.normalize(_item("Major Bitcoin exchange hack drains $100M from wallets"))
    assert event.category == EventCategory.HACK
    assert "BTCUSDT" in event.affected_symbols
    assert event.severity >= 0.9
    assert event.sentiment < 0


def test_duplicate_articles_collapse_into_single_event():
    normalizer = EventNormalizer()
    matcher = DuplicateDetector()
    memory = EventMemory()
    first = normalizer.normalize(
        _item("Binance halts withdrawals after wallet outage", source="coindesk")
    )
    second = normalizer.normalize(
        _item("Wallet outage forces Binance to pause withdrawals", source="cointelegraph")
    )
    memory.upsert(first, matcher)
    merged = memory.upsert(second, matcher)
    assert len(memory.events) == 1
    assert merged.mention_count == 2
    assert merged.evidence_count == 2


def test_time_decay_is_faster_for_exchange_outage_than_sec_event():
    from datetime import datetime

    normalizer = EventNormalizer()
    decay = TimeDecayEngine()
    now = datetime.now(tz=timezone.utc)
    exchange_event = normalizer.normalize(
        _item("Binance outage pauses withdrawals", source="binance_status"),
        now=now - timedelta(hours=12),
    )
    sec_event = normalizer.normalize(
        _item("SEC opens review on spot Bitcoin ETF filing", source="coindesk"),
        now=now - timedelta(hours=12),
    )
    exchange_event.last_seen_at = now - timedelta(hours=12)
    exchange_event.first_seen_at = now - timedelta(hours=12)
    sec_event.last_seen_at = now - timedelta(hours=12)
    sec_event.first_seen_at = now - timedelta(hours=12)
    assert decay.decay(exchange_event, now) < decay.decay(sec_event, now)


def test_lifecycle_transitions_detected_confirmed_escalating_resolved_expired():
    from datetime import datetime

    now = datetime.now(tz=timezone.utc)
    normalizer = EventNormalizer()
    matcher = DuplicateDetector()
    memory = EventMemory()
    base = normalizer.normalize(_item("Solana validator outage slows finality", source="coindesk"), now=now)
    out = memory.upsert(base, matcher, now=now)
    assert out.state == EventLifecycle.DETECTED

    second = normalizer.normalize(
        _item("Validators report Solana finality issues", source="cointelegraph"),
        now=now + timedelta(minutes=2),
    )
    out = memory.upsert(second, matcher, now=now + timedelta(minutes=2))
    assert out.state == EventLifecycle.CONFIRMED

    third = normalizer.normalize(
        _item("Solana outage escalates as more validators miss blocks", source="bitcoinmagazine"),
        now=now + timedelta(minutes=4),
    )
    out = memory.upsert(third, matcher, now=now + timedelta(minutes=4))
    assert out.state == EventLifecycle.ESCALATING

    resolved = normalizer.normalize(
        _item("Solana validators report issue resolved and blocks restored", source="coindesk"),
        now=now + timedelta(minutes=20),
    )
    out = memory.upsert(resolved, matcher, now=now + timedelta(minutes=20))
    assert out.state == EventLifecycle.RESOLVED

    memory.prune(now + timedelta(days=3))
    assert len(memory.events) == 0 or all(ev.state == EventLifecycle.EXPIRED for ev in memory.events.values())


def test_graph_propagation_reaches_multi_hop_assets():
    graph = EventGraph()
    weights = graph.impact_weights(["BTCUSDT"])
    assert weights["ETHUSDT"] > 0
    assert weights["ARBUSDT"] > 0
    assert weights["ARBUSDT"] < weights["ETHUSDT"]


def test_impact_engine_outputs_confidence_and_risk_modifiers():
    normalizer = EventNormalizer()
    impact = ImpactEngine()
    event = normalizer.normalize(_item("Major Binance hack triggers emergency wallet pause", source="coindesk"))
    decision = impact.assess("BTCUSDT", [event])
    assert decision.confidence_multiplier < 1.0
    assert decision.risk_multiplier > 1.0
    assert decision.signal_delay_s > 0
    assert decision.confidence_score > 0


def test_news_guard_dampen_returns_structured_surface_events():
    import asyncio

    guard = NewsGuard(Settings(_env_file=None))
    asyncio.run(
        guard.ingest([
            _item("Bitcoin ETF approval odds rise after SEC filing update", source="coindesk"),
            _item("Binance maintenance pauses withdrawals", source="binance_status"),
        ])
    )
    dampen, events = guard.dampen_for("BTCUSDT")
    assert 0.1 <= dampen <= 1.0
    assert events
    assert any("maintenance" in event.category or "etf" in event.category for event in events)
