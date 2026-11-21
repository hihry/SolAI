"""CLI entrypoint for quota-scheduler."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .jobs import ComputeJob
from .ledger import QuotaLedger
from .scheduler import FairScheduler
from .standin import WorkerPoolStandIn


def load_scheduler(
    spec_path: Path,
    pool_dir: Path | None = None,
    state_file: Path | None = None,
) -> FairScheduler:
    raw = json.loads(spec_path.read_text(encoding="utf-8"))
    worker_slots = int(raw.get("worker_slots", 4))
    tenants = raw.get("tenants", [])
    ceilings = {str(t["tenant_id"]): int(t["budget_units"]) for t in tenants}
    resolved_pool = pool_dir or (Path(os.environ["QUOTA_SCHEDULER_POOL_DIR"]) if os.environ.get("QUOTA_SCHEDULER_POOL_DIR") else None)
    pool = WorkerPoolStandIn(pool_dir=resolved_pool, max_slots_per_round=worker_slots, tenant_ceilings=ceilings) if resolved_pool else None
    sched = FairScheduler(ledger=QuotaLedger(), worker_slots=worker_slots, worker_pool=pool)
    for t in tenants:
        sched.ensure_tenant(str(t["tenant_id"]), quantum=int(t["quantum"]), budget_units=int(t["budget_units"]))
    for j in raw.get("jobs", []):
        sched.submit(ComputeJob.from_dict(j))
    if state_file is not None and state_file.exists():
        sched.restore_state(json.loads(state_file.read_text(encoding="utf-8")))
    return sched


def save_scheduler_state(sched: FairScheduler, state_file: Path) -> None:
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(sched.export_state(), indent=2, sort_keys=True), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="quota-scheduler")
    parser.add_argument("--workload", type=Path, required=True)
    parser.add_argument("--pool-dir", type=Path, default=None)
    parser.add_argument("--state-file", type=Path, default=None)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("ledger")
    sub.add_parser("backlog")
    step_parser = sub.add_parser("step")
    step_parser.add_argument("--rounds", type=int, default=1)

    args = parser.parse_args(argv)
    pool_dir = args.pool_dir
    if args.command == "step" and pool_dir is None and not os.environ.get("QUOTA_SCHEDULER_POOL_DIR"):
        pool_dir = args.workload.parent / "worker_pool"

    sched = load_scheduler(args.workload, pool_dir=pool_dir, state_file=args.state_file)
    if args.command == "ledger":
        print(json.dumps(sched.ledger.snapshot(), sort_keys=True))
        return 0
    if args.command == "backlog":
        print(json.dumps(sched.backlog_summary(), sort_keys=True))
        return 0
    if args.command == "step":
        raise NotImplementedError("step subcommand is not hooked up yet")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
