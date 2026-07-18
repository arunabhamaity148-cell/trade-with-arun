"""SQLite-backed signal lifecycle persistence."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

import aiosqlite

from twa.config import Settings
from twa.logging import get_logger
from twa.models.types import SignalIdea

log = get_logger("signal.store")

_OPEN_STATES = {"DETECTED", "ACTIVE", "TP1_HIT", "TP2_HIT"}
_TERMINAL_STATES = {"TP3_HIT", "STOPPED", "EXITED_EARLY", "EXPIRED"}


def _reference_entry_price(sig: SignalIdea) -> Optional[float]:
    if not sig.entry_zone:
        return None
    if len(sig.entry_zone) == 1:
        return float(sig.entry_zone[0])
    return float((sig.entry_zone[0] + sig.entry_zone[1]) / 2.0)


class SignalOutcomeStore:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.path: Path = settings.signal_outcomes_db_path
        self._conn: Optional[aiosqlite.Connection] = None

    async def start(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.path)
        await self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS signal_lifecycle (
                signal_id TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                side TEXT NOT NULL,
                regime TEXT NOT NULL,
                state TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                published_at TEXT,
                closed_at TEXT,
                entry_price REAL,
                invalidation REAL,
                targets_json TEXT NOT NULL,
                confidence REAL,
                raw_confidence REAL,
                outcome_note TEXT,
                outcome_pnl_bps REAL,
                payload_json TEXT NOT NULL
            )
            """
        )
        await self._conn.commit()

    async def stop(self) -> None:
        if self._conn is not None:
            await self._conn.commit()
            await self._conn.close()
            self._conn = None

    async def upsert_signal(
        self,
        sig: SignalIdea,
        *,
        state: str,
        outcome_note: str = "",
        outcome_pnl_bps: Optional[float] = None,
    ) -> None:
        if self._conn is None:
            await self.start()
        assert self._conn is not None
        ts_now = datetime.now(tz=timezone.utc).isoformat()
        created_at = sig.created_at.isoformat()
        updated_at = ts_now
        published_at = ts_now if state in {"ACTIVE", "TP1_HIT", "TP2_HIT", "TP3_HIT", "STOPPED", "EXITED_EARLY"} else None
        closed_at = ts_now if state in _TERMINAL_STATES else None
        await self._conn.execute(
            """
            INSERT INTO signal_lifecycle (
                signal_id, symbol, timeframe, side, regime, state, created_at, updated_at,
                published_at, closed_at, entry_price, invalidation, targets_json,
                confidence, raw_confidence, outcome_note, outcome_pnl_bps, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(signal_id) DO UPDATE SET
                state=excluded.state,
                updated_at=excluded.updated_at,
                published_at=COALESCE(signal_lifecycle.published_at, excluded.published_at),
                closed_at=COALESCE(excluded.closed_at, signal_lifecycle.closed_at),
                entry_price=COALESCE(signal_lifecycle.entry_price, excluded.entry_price),
                invalidation=excluded.invalidation,
                targets_json=excluded.targets_json,
                confidence=excluded.confidence,
                raw_confidence=excluded.raw_confidence,
                outcome_note=excluded.outcome_note,
                outcome_pnl_bps=excluded.outcome_pnl_bps,
                payload_json=excluded.payload_json
            """,
            (
                sig.id,
                sig.symbol,
                sig.timeframe.value,
                sig.side.value,
                sig.regime.value,
                state,
                created_at,
                updated_at,
                published_at,
                closed_at,
                _reference_entry_price(sig),
                sig.invalidation,
                json.dumps(sig.targets),
                sig.confidence,
                sig.raw_confidence,
                outcome_note,
                outcome_pnl_bps,
                sig.model_dump_json(),
            ),
        )
        await self._conn.commit()

    async def load_open_signals(self) -> List[Tuple[SignalIdea, str]]:
        if self._conn is None:
            await self.start()
        assert self._conn is not None
        cur = await self._conn.execute(
            """
            SELECT state, payload_json
            FROM signal_lifecycle
            WHERE state IN (?, ?, ?, ?)
            ORDER BY updated_at ASC
            """,
            tuple(_OPEN_STATES),
        )
        rows = await cur.fetchall()
        out: List[Tuple[SignalIdea, str]] = []
        for state, payload_json in rows:
            try:
                out.append((SignalIdea.model_validate_json(payload_json), str(state)))
            except Exception as exc:  # noqa: BLE001
                log.warning("signal.store.restore_failed", signal_state=state, err=str(exc))
        return out
