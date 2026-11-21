"""Baseline regression tests for quota-scheduler."""

from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
import tempfile
import unittest
from pathlib import Path

from src.cli import main as cli_main
from src.jobs import ComputeJob, TenantQueue
from src.ledger import QuotaLedger
from src.metrics import UtilizationTracker, compute_jains_fairness_index
from src.scheduler import FairScheduler
from src.standin import WorkerPoolStandIn


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

    def test_worker_pool_standin_and_cli_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            pool_dir = tmp_path / "pool"
            pool = WorkerPoolStandIn(pool_dir=pool_dir, max_slots_per_round=2, tenant_ceilings={"t1": 30})
            pool.begin_round(1)
            r1 = pool.dispatch_job(ComputeJob("j1", "t1", 20, "s3://b/1"))
            self.assertTrue(r1.accepted)
            r2 = pool.dispatch_job(ComputeJob("j2", "t1", 15, "s3://b/2"))
            self.assertFalse(r2.accepted)
            self.assertIn("quota_ceiling_breach", r2.reason)
            self.assertTrue((pool_dir / "dispatches.jsonl").exists())
            reloaded = WorkerPoolStandIn(pool_dir=pool_dir, max_slots_per_round=2)
            self.assertEqual(reloaded.snapshot()["quota_breach_events"], 1)

            workload = tmp_path / "workload.json"
            workload.write_text(
                json.dumps({
                    "worker_slots": 2,
                    "tenants": [{"tenant_id": "t1", "quantum": 20, "budget_units": 50}],
                    "jobs": [{"job_id": "j1", "tenant_id": "t1", "cost_units": 10, "payload_ref": "s3://b/1"}],
                }),
                encoding="utf-8",
            )
            out_ledger = io.StringIO()
            with redirect_stdout(out_ledger):
                self.assertEqual(cli_main(["--workload", str(workload), "ledger"]), 0)
            self.assertEqual(json.loads(out_ledger.getvalue())["t1"]["remaining"], 50)
            out_backlog = io.StringIO()
            with redirect_stdout(out_backlog):
                self.assertEqual(cli_main(["--workload", str(workload), "backlog"]), 0)
            self.assertEqual(json.loads(out_backlog.getvalue()), {"t1": 1})

    def test_scheduler_and_tracker_state_roundtrip(self) -> None:
        sched1 = FairScheduler(QuotaLedger(), worker_slots=1)
        sched1.ensure_tenant("alpha", quantum=50, budget_units=100)
        sched1.ensure_tenant("beta", quantum=50, budget_units=100)
        sched1.submit(ComputeJob("b1", "beta", 10, "s3://b/1"))
        sched1.ledger.charge("alpha", 40, job_id="a1")
        sched1.tracker.record_round({"alpha": 40}, dispatched_jobs=1, worker_slots=1)
        saved = sched1.export_state()

        sched2 = FairScheduler(QuotaLedger(), worker_slots=1)
        sched2.ensure_tenant("alpha", quantum=50, budget_units=100)
        sched2.ensure_tenant("beta", quantum=50, budget_units=100)
        sched2.restore_state(saved)
        self.assertEqual(sched2.tracker.cumulative_units(), {"alpha": 40})
        self.assertAlmostEqual(sched2.tracker.latest_fairness(), 1.0)
        sched2.tracker.record_round({"beta": 10}, dispatched_jobs=1, worker_slots=1)
        self.assertEqual(sched2.tracker.history()[-1]["round_index"], 2)
        self.assertAlmostEqual(sched2.tracker.latest_fairness(), compute_jains_fairness_index([40.0, 10.0]))

        legacy_state = {k: v for k, v in saved.items() if k != "tracker"}
        sched2.restore_state(legacy_state)
        self.assertEqual(sched2.tracker.cumulative_units(), {})
        self.assertEqual(sched2.tracker.history(), [])


if __name__ == "__main__":
    unittest.main()
