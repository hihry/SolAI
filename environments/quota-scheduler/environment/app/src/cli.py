"""CLI entrypoint for quota-scheduler."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .jobs import ComputeJob
from .ledger import QuotaLedger
from .scheduler import FairScheduler


def load_scheduler(spec_path: Path) -> FairScheduler:
    raw = json.loads(spec_path.read_text(encoding="utf-8"))
    ledger = QuotaLedger()
    sched = FairScheduler(ledger=ledger, worker_slots=int(raw.get("worker_slots", 4)))
    for t in raw.get("tenants", []):
        sched.ensure_tenant(t["tenant_id"], quantum=int(t["quantum"]), budget_units=int(t["budget_units"]))
    for j in raw.get("jobs", []):
        sched.submit(ComputeJob(**j))
    return sched


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="quota-scheduler")
    parser.add_argument("--workload", type=Path, required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("ledger")
    sub.add_parser("step")

    args = parser.parse_args(argv)
    sched = load_scheduler(args.workload)
    if args.command == "ledger":
        print(json.dumps(sched.ledger.snapshot(), sort_keys=True))
        return 0
    if args.command == "step":
        dispatched = sched.schedule_round()
        print(json.dumps({"dispatched": [j.job_id for j in dispatched], "ledger": sched.ledger.snapshot()}))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
