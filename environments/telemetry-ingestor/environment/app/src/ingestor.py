"""Adaptive telemetry ingestor coordinating buffer and sink."""

from __future__ import annotations

from .buffer import EventBuffer
from .schema import BatchSummary, TelemetryEvent, compute_service_rollup
from .sink import LocalJournalSink, TokenBucket


class AdaptiveIngestor:
    def __init__(
        self,
        buffer: EventBuffer,
        sink: LocalJournalSink,
        bucket: TokenBucket,
        max_retries: int = 4,
    ) -> None:
        self.buffer = buffer
        self.sink = sink
        self.bucket = bucket
        self.max_retries = max_retries

    def ingest(self, events: list[TelemetryEvent]) -> int:
        return self.buffer.enqueue(events)

    def pending_rollup(self, limit: int = 100) -> dict[str, dict[str, float]]:
        pending = [ev for ev, _ in self.buffer.fetch_pending(limit=limit, max_retries=self.max_retries)]
        return compute_service_rollup(pending)

    def drain_batch(self, batch_size: int = 10) -> BatchSummary:
        """Drain up to batch_size pending events within token-bucket and sink ceilings."""
        raise NotImplementedError("Adaptive batch drain with rate governance is not implemented yet")
