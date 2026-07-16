"""Helper module to build synthetic SignalIdea objects for tests."""
from datetime import datetime, timedelta, timezone
import hashlib

from twa.models.types import FactorContribution, SignalIdea, Side, RegimeLabel, Timeframe


def make_signal(symbol: str = "BTCUSDT", confidence: float = 0.5,
                side: Side = Side.LONG, regime: RegimeLabel = RegimeLabel.TREND_UP,
                timeframe: Timeframe = Timeframe.H1) -> SignalIdea:
    now = datetime.now(tz=timezone.utc)
    contribs = [
        FactorContribution(name="trend_strength_48", raw_value=0.7,
                           norm_value=0.7, weight=0.3, contribution=0.21,
                           rationale="test"),
    ]
    sig_id = hashlib.sha1(f"{symbol}|{now}|{confidence}|{side.value}".encode()).hexdigest()[:8]
    return SignalIdea(
        id=sig_id, symbol=symbol, exchange="test", timeframe=timeframe,
        side=side, regime=regime, confidence=confidence,
        expected_edge_bps=5.0 * confidence,
        entry_zone=[100.0, 100.5], targets=[102.0, 103.0, 104.0],
        invalidation=99.0 if side == Side.LONG else 101.5,
        rationale=["test rationale"], factor_contributions=contribs,
        created_at=now, expires_at=now + timedelta(minutes=5),
    )
