"""Baseline regression tests for telemetry-ingestor."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.buffer import EventBuffer
from src.schema import TelemetryEvent, compute_service_rollup
from src.sink import LocalJournalSink, SinkThrottledError, TokenBucket
from src.standin import CollectorState, LocalCollectorStandIn


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

    def test_local_collector_standin_accepts_and_throttles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audit_log = root / "audit.jsonl"
            accepted_log = root / "accepted.jsonl"
            state = CollectorState(audit_log, accepted_log, max_batch_size=2, max_requests=1, max_events=5, window_sec=10.0, retry_after_sec=0.1)
            standin = LocalCollectorStandIn(state)
            standin.start()
            try:
                sink = LocalJournalSink(root / "journal.jsonl", per_call_ceiling=2, collector_url=standin.url)
                ev1 = TelemetryEvent("s-1", "auth", "INFO", 8.5)
                ev2 = TelemetryEvent("s-2", "auth", "WARN", 12.0)
                self.assertEqual(sink.write_batch([ev1]), ["s-1"])
                with self.assertRaises(SinkThrottledError) as ctx:
                    sink.write_batch([ev2])
                self.assertEqual(ctx.exception.status_code, 429)
            finally:
                standin.stop()
            audit_rows = [json.loads(line) for line in audit_log.read_text(encoding="utf-8").splitlines()]
            self.assertEqual([r["status"] for r in audit_rows], [200, 429])
            accepted_rows = [json.loads(line) for line in accepted_log.read_text(encoding="utf-8").splitlines()]
            self.assertEqual([r["event_id"] for r in accepted_rows], ["s-1"])


if __name__ == "__main__":
    unittest.main()
