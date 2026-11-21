"""Baseline regression tests for quota-scheduler."""

from __future__ import annotations

import unittest

from src.jobs import ComputeJob, TenantQueue
from src.ledger import QuotaLedger
from src.metrics import UtilizationTracker, compute_jains_fairness_index
from src.scheduler import FairScheduler


class SchedulerRegressionTests(unittest.TestCase):
    def test_tenant_queue_fifo_and_validation(self) -> None:
        q = TenantQueue("team-alpha", quantum=50)
        j1 = ComputeJob("j1", "team-alpha", 20, "s3://b/1")
        j2 = ComputeJob("j2", "team-alpha", 30, "s3://b/2")
        q.push(j1)
        q.push(j2)
        self.assertEqual(len(q), 2)
        self.assertEqual(q.pop().job_id, "j1")
        with self.assertRaises(ValueError):
            q.push(ComputeJob("j3", "other-team", 10, "s3://b/3"))

    def test_quota_ledger_enforces_ceiling(self) -> None:
        ledger = QuotaLedger()
        ledger.register_tenant("team-alpha", budget_units=45)
        self.assertTrue(ledger.can_afford("team-alpha", 30))
        self.assertEqual(ledger.charge("team-alpha", 30), 15)
        self.assertFalse(ledger.can_afford("team-alpha", 20))
        with self.assertRaises(RuntimeError):
            ledger.charge("team-alpha", 20)

    def test_fairness_index_and_backlog_accounting(self) -> None:
        self.assertAlmostEqual(compute_jains_fairness_index([50.0, 50.0, 50.0]), 1.0)
        self.assertAlmostEqual(compute_jains_fairness_index([100.0, 0.0]), 0.5)

        tracker = UtilizationTracker()
        rec = tracker.record_round({"t1": 40, "t2": 40}, dispatched_jobs=2)
        self.assertEqual(rec.round_index, 1)
        self.assertAlmostEqual(tracker.latest_fairness(), 1.0)

        sched = FairScheduler(QuotaLedger(), worker_slots=2, tracker=tracker)
        sched.ensure_tenant("t1", quantum=25, budget_units=100)
        sched.submit(ComputeJob("j9", "t1", 15, "s3://b/9"))
        self.assertEqual(sched.backlog_summary(), {"t1": 1})


if __name__ == "__main__":
    unittest.main()
