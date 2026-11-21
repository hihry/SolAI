"""Baseline regression tests for telemetry-ingestor."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.buffer import EventBuffer
from src.schema import TelemetryEvent, compute_service_rollup
from src.sink import LocalJournalSink, TokenBucket


class TelemetryRegressionTests(unittest.TestCase):
    def test_event_validation_and_rollup(self) -> None:
        events = [
            TelemetryEvent("e1", "auth", "INFO", 12.5, {"region": "use1"}),
            TelemetryEvent("e2", "auth", "WARN", 27.5, {"region": "use1"}),
            TelemetryEvent("e3", "billing", "ERROR", 40.0, {}),
        ]
        rollup = compute_service_rollup(events)
        self.assertEqual(rollup["auth"]["count"], 2.0)
        self.assertAlmostEqual(rollup["auth"]["avg_ms"], 20.0)
        self.assertEqual(rollup["billing"]["p95_ms"], 40.0)

    def test_buffer_idempotency_and_token_bucket(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            buf = EventBuffer(Path(tmp) / "queue.db")
            ev = TelemetryEvent("ev-1", "gateway", "INFO", 5.2)
            self.assertEqual(buf.enqueue([ev, ev]), 1)
            self.assertEqual(buf.counts_by_status()["pending"], 1)

            bucket = TokenBucket(capacity=4, tokens=2, refill_per_tick=1.0)
            self.assertTrue(bucket.try_acquire(2))
            self.assertFalse(bucket.try_acquire(1))
            bucket.advance(2.0)
            self.assertTrue(bucket.try_acquire(2))

            sink = LocalJournalSink(Path(tmp) / "out.jsonl", per_call_ceiling=2)
            written = sink.write_batch([ev])
            self.assertEqual(written, ["ev-1"])


if __name__ == "__main__":
    unittest.main()
