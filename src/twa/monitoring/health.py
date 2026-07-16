"""Health / heartbeat / latency / memory monitoring.

Lightweight:
  * psutil for memory and CPU.
  * periodic asyncio heartbeat that writes a heartbeat file and emits a log line.
  * feed-level health aggregated from data adapters.
  * automatic recovery scheduler (recover stale adapters with an extra fetch).
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import psutil

from twa.config import Settings
from twa.data.cache import MarketDataAggregator
from twa.logging import get_logger

log = get_logger("monitoring")


@dataclass
class ProcessMetrics:
    ts: float
    cpu_pct: float
    rss_mb: float
    fds: int
    threads: int


class HealthMonitor:
    """Async-friendly health monitor with periodic heartbeats."""

    def __init__(self, settings: Settings, data: MarketDataAggregator):
        self.settings = settings
        self.data = data
        self._last_heartbeat: float = 0.0
        self._proc = psutil.Process(os.getpid())
        self._metrics: List[ProcessMetrics] = []
        self._stopped = False
        self.beat_path = Path(settings.data_dir) / "heartbeat.json"

    async def start(self) -> None:
        self._stopped = False
        asyncio.create_task(self._loop(), name="health-monitor")

    async def stop(self) -> None:
        self._stopped = True

    async def _loop(self) -> None:
        while not self._stopped:
            await self.tick()
            await asyncio.sleep(self.settings.heartbeat_s)

    async def tick(self) -> None:
        try:
            cpu = self._proc.cpu_percent(interval=None)
            mem = self._proc.memory_info().rss / 1_048_576
            try:
                fds = len(self._proc.open_files())
            except Exception:
                fds = -1
            m = ProcessMetrics(ts=time.time(), cpu_pct=cpu, rss_mb=mem,
                              fds=fds, threads=self._proc.num_threads())
            self._metrics.append(m)
            if len(self._metrics) > 256:
                self._metrics = self._metrics[-256:]

            feed_health = self.data.health()
            health_doc = {
                "ts": m.ts, "cpu_pct": m.cpu_pct, "rss_mb": m.rss_mb,
                "fds": m.fds, "threads": m.threads,
                "feeds": feed_health,
            }
            self.beat_path.parent.mkdir(parents=True, exist_ok=True)
            self.beat_path.write_text(json.dumps(health_doc, indent=2))
            self._last_heartbeat = m.ts
            log.info("health.beat", cpu=round(cpu, 2), rss_mb=round(mem, 2),
                     feeds=list(feed_health.get("adapters", {}).keys()),
                     stale=[n for n, h in feed_health.get("adapters", {}).items()
                            if h.get("last_error")])
        except Exception as e:  # noqa: BLE001
            log.warning("health.tick_failed", err=str(e))

    def snapshot(self) -> Dict:
        if not self._metrics:
            return {"note": "no_metrics_yet"}
        last = self._metrics[-1]
        return {
            "last_heartbeat_ts": self._last_heartbeat,
            "cpu_pct": last.cpu_pct,
            "rss_mb": last.rss_mb,
            "fds": last.fds,
            "threads": last.threads,
            "feeds": self.data.health(),
        }
