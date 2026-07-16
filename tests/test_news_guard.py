"""News guard tests."""
from datetime import datetime, timedelta, timezone

from twa.config import Settings
from twa.news.guard import NewsGuard
from twa.models.types import NewsEvent


def test_critical_keywords_severity_classified_high():
    g = NewsGuard(Settings(_env_file=None))
    sev, sent, cat = NewsGuard._classify(g, "Major exchange hacked — $100M stolen")
    assert sev >= 0.99
    assert sent < 0
    assert cat == "critical"


def test_bullish_news_classification():
    g = NewsGuard(Settings(_env_file=None))
    sev, sent, cat = NewsGuard._classify(g, "ETF approval expected next week")
    assert sev >= 0.5
    assert sent > 0


def test_btc_pattern_detected():
    g = NewsGuard(Settings(_env_file=None))
    syms = NewsGuard._detect_symbols(g, "Bitcoin ETF approval is bullish")
    assert "BTCUSDT" in syms


def test_dampen_handles_empty_cache():
    g = NewsGuard(Settings(_env_file=None))
    nd, events = g.dampen_for("BTCUSDT")
    assert nd == 1.0
    assert events == []


def test_dampen_suppresses_for_critical_recent(monkeypatch):
    g = NewsGuard(Settings(_env_file=None))
    recent_critical = NewsEvent(
        title="Massive exchange hack", source="rss", url="x",
        published_at=datetime.now(tz=timezone.utc),
        symbols=["BTCUSDT"], severity=1.0, sentiment=-0.4, category="critical",
    )
    g._cache.append(recent_critical)
    nd, events = g.dampen_for("BTCUSDT")
    assert nd <= 0.2
    assert events
