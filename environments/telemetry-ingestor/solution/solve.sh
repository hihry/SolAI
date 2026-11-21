#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/app}"

cat > "$APP_DIR/src/ingestor.py" <<'PY'
"""Adaptive telemetry ingestor coordinating buffer and sink."""

from __future__ import annotations

import time

from .buffer import EventBuffer
from .schema import BatchSummary, IngestorConfig, TelemetryEvent, compute_backoff_delay, compute_service_rollup
from .sink import LocalJournalSink, SinkRejectedError, SinkThrottledError, TokenBucket


class AdaptiveIngestor:
    def __init__(
        self,
        buffer: EventBuffer,
        sink: LocalJournalSink,
        bucket: TokenBucket,
        max_retries: int = 4,
        config: IngestorConfig | None = None,
    ) -> None:
        self.buffer = buffer
        self.sink = sink
        self.bucket = bucket
        self.config = config or IngestorConfig(max_retries=max_retries)
        self.max_retries = self.config.max_retries

    def ingest(self, events: list[TelemetryEvent]) -> int:
        return self.buffer.enqueue(events)

    def pending_rollup(self, limit: int = 100) -> dict[str, dict[str, float]]:
        pending = [ev for ev, _ in self.buffer.fetch_pending(limit=limit, max_retries=self.max_retries)]
        return compute_service_rollup(pending)

    def drain_batch(self, batch_size: int = 10) -> BatchSummary:
        """Drain up to batch_size pending events within token-bucket and sink ceilings."""
        if batch_size <= 0:
            return BatchSummary()
        pending_rows = self.buffer.fetch_pending(limit=batch_size, max_retries=self.max_retries)
        if not pending_rows:
            return BatchSummary()

        attempted = len(pending_rows)
        admitted: list[TelemetryEvent] = []
        for ev, _ in pending_rows:
            if self.bucket.try_acquire(1):
                admitted.append(ev)

        if not admitted:
            return BatchSummary(attempted=attempted, flushed=0, deferred=attempted, mean_latency_ms=0.0)

        ceiling = max(1, int(getattr(self.sink, "per_call_ceiling", 25)))
        max_attempts = max(1, min(self.config.max_drain_attempts, 2))
        flushed_events: list[TelemetryEvent] = []
        flushed_ids: set[str] = set()

        for start in range(0, len(admitted), ceiling):
            chunk = admitted[start : start + ceiling]
            delivered = False
            for attempt in range(max_attempts):
                try:
                    accepted = self.sink.write_batch(chunk)
                    self.buffer.mark_flushed(accepted)
                    accepted_set = set(accepted)
                    for ev in chunk:
                        if ev.event_id in accepted_set and ev.event_id not in flushed_ids:
                            flushed_ids.add(ev.event_id)
                            flushed_events.append(ev)
                    delivered = True
                    break
                except SinkThrottledError as exc:
                    if attempt + 1 < max_attempts:
                        delay = min(
                            max(0.0, exc.retry_after_sec),
                            compute_backoff_delay(attempt, self.config.base_backoff_sec, self.config.max_backoff_sec),
                            0.25,
                        )
                        if delay > 0:
                            time.sleep(delay)
                        continue
                    self.buffer.record_retry([ev.event_id for ev in chunk])
                    break
                except (SinkRejectedError, RuntimeError):
                    self.buffer.record_retry([ev.event_id for ev in chunk])
                    break
            if not delivered:
                break

        flushed_count = len(flushed_events)
        mean_ms = (
            sum(ev.latency_ms for ev in flushed_events) / flushed_count
            if flushed_count > 0
            else 0.0
        )
        return BatchSummary(
            attempted=attempted,
            flushed=flushed_count,
            deferred=attempted - flushed_count,
            mean_latency_ms=mean_ms,
        )
PY
