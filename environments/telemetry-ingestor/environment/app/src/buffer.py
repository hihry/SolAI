"""SQLite-backed local WAL queue for telemetry events."""

from __future__ import annotations

from contextlib import closing
import json
import sqlite3
from pathlib import Path
from typing import Iterable

from .schema import TelemetryEvent


class EventBuffer:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS events ("
                "event_id TEXT PRIMARY KEY, service TEXT NOT NULL, level TEXT NOT NULL, "
                "latency_ms REAL NOT NULL, payload_json TEXT NOT NULL, "
                "status TEXT NOT NULL DEFAULT 'pending', retries INTEGER NOT NULL DEFAULT 0)"
            )

    def enqueue(self, events: Iterable[TelemetryEvent]) -> int:
        inserted = 0
        with closing(self._connect()) as conn, conn:
            for ev in events:
                ev.validate()
                cur = conn.execute(
                    "INSERT OR IGNORE INTO events (event_id, service, level, latency_ms, payload_json, status, retries) "
                    "VALUES (?, ?, ?, ?, ?, 'pending', 0)",
                    (ev.event_id, ev.service, ev.level, ev.latency_ms, json.dumps(ev.payload, sort_keys=True)),
                )
                inserted += cur.rowcount
        return inserted

    def fetch_pending(self, limit: int, max_retries: int = 5) -> list[tuple[TelemetryEvent, int]]:
        if limit <= 0:
            return []
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT event_id, service, level, latency_ms, payload_json, retries "
                "FROM events WHERE status = 'pending' AND retries < ? ORDER BY retries ASC, rowid ASC LIMIT ?",
                (max_retries, limit),
            ).fetchall()
        return [
            (
                TelemetryEvent(row["event_id"], row["service"], row["level"], float(row["latency_ms"]), json.loads(row["payload_json"])),
                int(row["retries"]),
            )
            for row in rows
        ]

    def mark_flushed(self, event_ids: list[str]) -> None:
        if not event_ids:
            return
        with closing(self._connect()) as conn, conn:
            conn.executemany(
                "UPDATE events SET status = 'flushed' WHERE event_id = ?",
                [(eid,) for eid in event_ids],
            )

    def record_retry(self, event_ids: list[str]) -> None:
        if not event_ids:
            return
        with closing(self._connect()) as conn, conn:
            conn.executemany(
                "UPDATE events SET retries = retries + 1 WHERE event_id = ?",
                [(eid,) for eid in event_ids],
            )

    def counts_by_status(self) -> dict[str, int]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS cnt FROM events GROUP BY status"
            ).fetchall()
        return {row["status"]: int(row["cnt"]) for row in rows}

    def get_event_retries(self, event_id: str) -> int | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT retries FROM events WHERE event_id = ?",
                (event_id,),
            ).fetchone()
        return int(row["retries"]) if row is not None else None

    def dead_letter_count(self, max_retries: int = 4) -> int:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM events WHERE status = 'pending' AND retries >= ?",
                (max_retries,),
            ).fetchone()
        return int(row["cnt"]) if row is not None else 0

    def flush_history_summary(self, max_retries: int = 4) -> dict[str, int]:
        counts = self.counts_by_status()
        dead = self.dead_letter_count(max_retries=max_retries)
        pending_total = counts.get("pending", 0)
        flushed = counts.get("flushed", 0)
        return {
            "flushed": flushed,
            "pending_eligible": max(0, pending_total - dead),
            "dead_lettered": dead,
            "total": flushed + pending_total,
        }
