"""SQLite-backed signal lifecycle persistence."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import aiosqlite

from twa.config import Settings
from twa.models.types import SignalIdea


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

    async def upsert_signal(self, sig: SignalIdea, *, state: str, outcome_note: str = "", outcome_pnl_bps: Optional[float] = None) -> None:
        if self._conn is None:
            await self.start()
        assert self._conn is not None
        created_at = sig.created_at.isoformat()
        updated_at = sig.created_at.isoformat()
        published_at = sig.created_at.isoformat() if state in {"ACTIVE", "TP1_HIT", "TP2_HIT", "TP3_HIT", "STOPPED", "EXITED_EARLY"} else None
        closed_at = sig.created_at.isoformat() if state in {"TP3_HIT", "STOPPED", "EXITED_EARLY", "EXPIRED"} else None
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
                published_at=COALESCE(excluded.published_at, signal_lifecycle.published_at),
                closed_at=COALESCE(excluded.closed_at, signal_lifecycle.closed_at),
                entry_price=COALESCE(excluded.entry_price, signal_lifecycle.entry_price),
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
                sig.entry_zone[0] if sig.entry_zone else None,
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
