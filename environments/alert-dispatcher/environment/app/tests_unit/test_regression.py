"""Baseline regression tests for alert-dispatcher."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.dedup import Deduplicator
from src.formatter import SummaryFormatter, is_plain_text
from src.incidents import IncidentSignal
from src.router import (
    AlertRouter, ChannelPolicy, MaintenanceSilence, SilenceRegistry, validate_channel_name,
)
from src.standin import LocalWebhookServer, LocalWebhookStandIn, post_to_local_webhook


class AlertDispatcherRegressionTests(unittest.TestCase):
    def test_dedup_escalation_and_priority_order(self) -> None:
        dedup = Deduplicator()
        dedup.observe(IncidentSignal("i1", "db-primary", "MEDIUM", "replica lag elevated", "db-lag"))
        dedup.observe(IncidentSignal("i2", "db-primary", "CRITICAL", "replica lag elevated", "db-lag"))
        dedup.observe(IncidentSignal("i3", "cache", "HIGH", "eviction spike", "cache-evict"))

        ordered = dedup.top_incidents()
        self.assertEqual(len(ordered), 2)
        self.assertEqual((ordered[0].subsystem, ordered[0].peak_severity, ordered[0].occurrences), ("db-primary", "CRITICAL", 2))
        self.assertEqual((dedup.total_observed, dedup.group_count, dedup.severity_counts()["CRITICAL"]), (3, 2, 1))

    def test_origin_validation_blocks_unlisted_domains(self) -> None:
        fmt = SummaryFormatter({"https://status.internal.example"})
        url = fmt.build_status_url("https://status.internal.example", "db-lag")
        self.assertEqual(url, "https://status.internal.example/status/runbooks/db-lag")
        for bad in (
            "http://status.internal.example", "https://external.invalid",
            "https://user@status.internal.example", "https://status.internal.example/extra",
            "https://status.internal.example?next=1",
        ):
            with self.assertRaises(ValueError):
                fmt.build_status_url(bad, "db-lag")
        self.assertTrue(is_plain_text("[CRITICAL] db-primary (x2): lag"))
        self.assertTrue(is_plain_text("[HIGH] api-gw (x1): latency < 50ms | a < b"))
        self.assertTrue(is_plain_text("[HIGH] api-gw (x1): latency < 50ms | a:b < c"))
        self.assertFalse(is_plain_text("<form action='/login'><input type='password'></form>"))
        self.assertFalse(is_plain_text("<div>Verify password</div>"))
        self.assertFalse(is_plain_text("<template>Verify</template>"))
        self.assertFalse(is_plain_text("<span onclick='x'>Verify</span>"))
        self.assertFalse(is_plain_text("&lt;div&gt;Verify&lt;/div&gt;"))
        self.assertFalse(is_plain_text("<login_box>Verify</login_box>"))
        self.assertFalse(is_plain_text("<svg:form>Verify</svg:form>"))

    def test_signal_validation_and_channel_policy(self) -> None:
        for sig in (
            IncidentSignal("i1", "", "LOW", "msg", "slug"),
            IncidentSignal("i1", "db", "LOW", "line1\nline2", "slug"),
            IncidentSignal("i1", "db", "LOW", "msg", "-bad-slug-"),
        ):
            with self.assertRaises(ValueError):
                sig.validate()
        self.assertEqual(validate_channel_name("oncall-ops_1"), "oncall-ops_1")
        for bad_ch in ("", "../escape", ".hidden", "team/ops"):
            with self.assertRaises(ValueError):
                validate_channel_name(bad_ch)
        self.assertEqual(ChannelPolicy("oncall-ops", min_severity="HIGH", max_items=5).max_items, 5)

    def test_maintenance_silence_preserves_critical_alerts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            silences = SilenceRegistry()
            silences.register(MaintenanceSilence("m1", "batch-", "MEDIUM"))
            with self.assertRaises(ValueError):
                MaintenanceSilence("m2", "batch-", "CRITICAL")

            fmt = SummaryFormatter({"https://status.internal.example"})
            router = AlertRouter(fmt, "https://status.internal.example", Path(tmp), silences)
            stats = router.ingest_signals([
                IncidentSignal("s1", "batch-etl", "LOW", "scheduled drain", "etl-drain"),
                IncidentSignal("s2", "batch-etl", "CRITICAL", "checkpoint failure", "etl-fail"),
            ])
            self.assertEqual(stats, {"accepted": 1, "silenced": 1})
            lines = router.preview_lines()
            self.assertEqual(len(lines), 1)
            self.assertIn("[CRITICAL] batch-etl", lines[0])

    def test_local_webhook_standin_and_server_record_deliveries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp) / "standin"
            standin = LocalWebhookStandIn(state_dir)
            rec = standin.deliver(
                channel="oncall-ops",
                body="[HIGH] cache (x1): spike | ref=https://status.internal.example/status/runbooks/cache",
            )
            self.assertEqual(rec.content_type, "text/plain")
            self.assertTrue(Path(rec.payload_path).exists())
            self.assertEqual(len(standin.read_deliveries()), 1)

            with LocalWebhookServer(state_dir, host="127.0.0.1", port=0) as srv:
                resp = post_to_local_webhook(srv.url, "oncall-ops", "digest payload")
                self.assertEqual(resp["status"], "accepted")
            self.assertEqual(len(standin.read_deliveries()), 2)
            with self.assertRaises(ValueError):
                post_to_local_webhook("https://external.invalid/webhook", "ops", "hi")

            ipv6_rec = standin.deliver(
                channel="edge-urls",
                body="a=https://[2001:db8::1]/login b=https://[fe80::1%25eth0]/login c=https://status.internal.example:99999/status d=https://[evil/login",
            )
            self.assertIn("https://[2001:db8::1]/login", ipv6_rec.extracted_urls)
            self.assertIn("https://[fe80::1%25eth0]/login", ipv6_rec.extracted_urls)
            self.assertIn("https://status.internal.example:99999/status", ipv6_rec.extracted_urls)
            self.assertIn("https://[evil/login", ipv6_rec.extracted_urls)
            self.assertEqual(ipv6_rec.origins, ["https://[2001:db8::1]", "https://[fe80::1%25eth0]"])


if __name__ == "__main__":
    unittest.main()
