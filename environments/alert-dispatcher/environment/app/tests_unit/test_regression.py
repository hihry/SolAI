"""Baseline regression tests for alert-dispatcher."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.dedup import Deduplicator
from src.formatter import SummaryFormatter
from src.incidents import IncidentSignal
from src.router import AlertRouter, MaintenanceSilence, SilenceRegistry


class AlertDispatcherRegressionTests(unittest.TestCase):
    def test_dedup_escalation_and_priority_order(self) -> None:
        dedup = Deduplicator()
        dedup.observe(IncidentSignal("i1", "db-primary", "MEDIUM", "replica lag elevated", "db-lag"))
        dedup.observe(IncidentSignal("i2", "db-primary", "CRITICAL", "replica lag elevated", "db-lag"))
        dedup.observe(IncidentSignal("i3", "cache", "HIGH", "eviction spike", "cache-evict"))

        ordered = dedup.top_incidents()
        self.assertEqual(len(ordered), 2)
        self.assertEqual(ordered[0].subsystem, "db-primary")
        self.assertEqual(ordered[0].peak_severity, "CRITICAL")
        self.assertEqual(ordered[0].occurrences, 2)

    def test_origin_validation_blocks_unlisted_domains(self) -> None:
        fmt = SummaryFormatter({"https://status.internal.example"})
        url = fmt.build_status_url("https://status.internal.example", "db-lag")
        self.assertEqual(url, "https://status.internal.example/status/runbooks/db-lag")
        with self.assertRaises(ValueError):
            fmt.build_status_url("http://status.internal.example", "db-lag")
        with self.assertRaises(ValueError):
            fmt.build_status_url("https://external.invalid", "db-lag")

    def test_maintenance_silence_preserves_critical_alerts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            silences = SilenceRegistry()
            silences.register(MaintenanceSilence("m1", "batch-", "MEDIUM"))
            with self.assertRaises(ValueError):
                MaintenanceSilence("m2", "batch-", "CRITICAL")

            fmt = SummaryFormatter({"https://status.internal.example"})
            router = AlertRouter(fmt, "https://status.internal.example", Path(tmp), silences)
            stats = router.ingest_signals(
                [
                    IncidentSignal("s1", "batch-etl", "LOW", "scheduled drain", "etl-drain"),
                    IncidentSignal("s2", "batch-etl", "CRITICAL", "checkpoint failure", "etl-fail"),
                ]
            )
            self.assertEqual(stats, {"accepted": 1, "silenced": 1})
            lines = router.preview_lines()
            self.assertEqual(len(lines), 1)
            self.assertIn("[CRITICAL] batch-etl", lines[0])


if __name__ == "__main__":
    unittest.main()
