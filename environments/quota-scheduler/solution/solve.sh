#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/app}"

APP_DIR="$APP_DIR" python3 -B - <<'PY'
import os
from pathlib import Path

app_dir = Path(os.environ["APP_DIR"])
sched_path = app_dir / "src" / "scheduler.py"
cli_path = app_dir / "src" / "cli.py"

sched_src = sched_path.read_text(encoding="utf-8")
old_sched = '''    def schedule_round(self) -> list[ComputeJob]:
        """Dispatch up to worker_slots jobs using Deficit Round Robin and QuotaLedger enforcement."""
        raise NotImplementedError("Deficit Round Robin scheduling round is not implemented yet")'''

new_sched = '''    def schedule_round(self) -> list[ComputeJob]:
        """Dispatch up to worker_slots jobs using Deficit Round Robin and QuotaLedger enforcement."""
        self._round_counter += 1
        round_id = self._round_counter
        if self.worker_pool is not None:
            round_id = self.worker_pool.begin_round(max(self._round_counter, self.worker_pool.current_round_id + 1))

        dispatched: list[ComputeJob] = []
        units_by_tenant: dict[str, int] = {}
        deferred: dict[str, str] = {}
        turns = len(self.active_order)

        for _ in range(turns):
            if len(dispatched) >= self.worker_slots or not self.active_order:
                break
            tid = self.active_order.popleft()
            queue = self.queues[tid]
            head = queue.peek()
            if head is None:
                queue.reset_if_empty()
                continue
            if not self.ledger.can_afford(tid, head.cost_units):
                deferred[tid] = "quota_exhausted"
                self.active_order.append(tid)
                continue

            queue.add_quantum()
            while len(dispatched) < self.worker_slots:
                head = queue.peek()
                if head is None:
                    break
                reason = queue.defer_reason(self.ledger.remaining_for(tid))
                if reason is not None:
                    deferred[tid] = reason
                    break
                queue.deficit -= head.cost_units
                job = queue.pop()
                self.ledger.charge(tid, job.cost_units, job_id=job.job_id)
                if self.worker_pool is not None:
                    self.worker_pool.dispatch_job(job, round_id=round_id)
                dispatched.append(job)
                units_by_tenant[tid] = units_by_tenant.get(tid, 0) + job.cost_units

            if len(queue) > 0:
                self.active_order.append(tid)

        self.tracker.record_round(
            units_by_tenant,
            dispatched_jobs=len(dispatched),
            worker_slots=self.worker_slots,
            deferred=deferred,
        )
        if self.worker_pool is not None:
            self.worker_pool.end_round(round_id)
        return dispatched'''

if old_sched not in sched_src:
    raise RuntimeError("Expected unfinished schedule_round block not found in scheduler.py")
sched_path.write_text(sched_src.replace(old_sched, new_sched, 1), encoding="utf-8")

cli_src = cli_path.read_text(encoding="utf-8")
old_cli = '''    if args.command == "step":
        raise NotImplementedError("step subcommand is not hooked up yet")'''

new_cli = '''    if args.command == "step":
        if args.rounds <= 0:
            raise ValueError("--rounds must be positive")
        all_dispatched: list[str] = []
        for _ in range(args.rounds):
            all_dispatched.extend(j.job_id for j in sched.schedule_round())
        if args.state_file is not None:
            save_scheduler_state(sched, args.state_file)
        payload = {
            "dispatched": all_dispatched,
            "ledger": sched.ledger.snapshot(),
            "backlog": sched.backlog_summary(),
            "fairness_index": sched.tracker.latest_fairness(),
            "pool": sched.worker_pool.snapshot() if sched.worker_pool is not None else None,
        }
        print(json.dumps(payload, sort_keys=True))
        return 0'''

if old_cli not in cli_src:
    raise RuntimeError("Expected unfinished step block not found in cli.py")
cli_path.write_text(cli_src.replace(old_cli, new_cli, 1), encoding="utf-8")
PY
