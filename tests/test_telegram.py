"""Telegram rendering tests (no real network calls)."""
from datetime import datetime, timezone
import hashlib

from twa.models.types import FactorContribution, SignalIdea, RegimeLabel, Side, Timeframe
from twa.telegram.bot import render_signal, render_status


def _mk_sig(confidence: float, side: Side) -> SignalIdea:
    now = datetime.now(tz=timezone.utc)
    return SignalIdea(
        id=hashlib.sha1(f"{side}|{confidence}|{now}".encode()).hexdigest()[:8],
        symbol="BTCUSDT", exchange="binance", timeframe=Timeframe.H1,
        side=side, regime=RegimeLabel.TREND_UP, confidence=confidence,
        expected_edge_bps=7.0, entry_zone=[29_900, 30_100],
        targets=[30_600, 31_200, 31_800], invalidation=29_400,
        rationale=["rule-based"], factor_contributions=[
            FactorContribution(name="trend_strength_48", raw_value=0.7,
                               norm_value=0.7, weight=0.3, contribution=0.21,
                               rationale="trend up"),
        ],
        created_at=now,
        expires_at=now.replace(tzinfo=timezone.utc) if now.tzinfo else now,
    )


def test_render_signal_contains_core_fields():
    for side in (Side.LONG, Side.SHORT, Side.NEUTRAL):
        text = render_signal(_mk_sig(0.72, side))
        assert "BTCUSDT" in text
        assert "Entry zone" in text
        assert "TP1" in text and "TP2" in text and "TP3" in text
        assert "Invalidation / SL" in text
        assert "Expected edge" in text
        assert "Signal ID" in text
        assert "TRADE WITH ARUN" not in text
        assert "no orders are placed" in text.lower() or "signal only" in text.lower()


def test_render_status_minimal():
    text = render_status("LONG", "trend_up", 0.5, ["vol=0.2", "oi=120"])
    assert "LONG" in text
    assert "trend\\_up" in text
    assert "0.50" in text
    assert "vol=0.2" in text
