"""SQLite-backed local WAL queue for telemetry events."""

from __future__ import annotations

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
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    event_id TEXT PRIMARY KEY,
                    service TEXT NOT NULL,
                    level TEXT NOT NULL,
                    latency_ms REAL NOT NULL,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    retries INTEGER NOT NULL DEFAULT 0
                )
                """
            )

    def enqueue(self, events: Iterable[TelemetryEvent]) -> int:
        inserted = 0
        with self._connect() as conn:
            for ev in events:
                ev.validate()
                cur = conn.execute(
                    """
                    INSERT OR IGNORE INTO events
                    (event_id, service, level, latency_ms, payload_json, status, retries)
                    VALUES (?, ?, ?, ?, ?, 'pending', 0)
                    """,
                    (
                        ev.event_id,
                        ev.service,
                        ev.level,
                        ev.latency_ms,
                        json.dumps(ev.payload, sort_keys=True),
                    ),
                )
                inserted += cur.rowcount
        return inserted

    def fetch_pending(self, limit: int, max_retries: int = 5) -> list[tuple[TelemetryEvent, int]]:
        if limit <= 0:
            return []
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT event_id, service, level, latency_ms, payload_json, retries
                FROM events
                WHERE status = 'pending' AND retries < ?
                ORDER BY retries ASC, rowid ASC
                LIMIT ?
                """,
                (max_retries, limit),
            ).fetchall()
        results: list[tuple[TelemetryEvent, int]] = []
        for row in rows:
            ev = TelemetryEvent(
                event_id=row["event_id"],
                service=row["service"],
                level=row["level"],
                latency_ms=float(row["latency_ms"]),
                payload=json.loads(row["payload_json"]),
            )
            results.append((ev, int(row["retries"])))
        return results

    def mark_flushed(self, event_ids: list[str]) -> None:
        if not event_ids:
            return
        with self._connect() as conn:
            conn.executemany(
                "UPDATE events SET status = 'flushed' WHERE event_id = ?",
                [(eid,) for eid in event_ids],
            )

    def record_retry(self, event_ids: list[str]) -> None:
        if not event_ids:
            return
        with self._connect() as conn:
            conn.executemany(
                "UPDATE events SET retries = retries + 1 WHERE event_id = ?",
                [(eid,) for eid in event_ids],
            )

    def counts_by_status(self) -> dict[str, int]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS cnt FROM events GROUP BY status"
            ).fetchall()
        return {row["status"]: int(row["cnt"]) for row in rows}
