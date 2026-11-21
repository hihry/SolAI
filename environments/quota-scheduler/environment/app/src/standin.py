"""Local disk-backed worker-pool stand-in recording all dispatch attempts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path

from .jobs import ComputeJob


@dataclass(frozen=True)
class PoolReceipt:
    round_id: int
    seq: int
    job_id: str
    tenant_id: str
    cost_units: int
    accepted: bool
    reason: str
    round_slots_used: int
    tenant_cumulative_units: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class WorkerPoolStandIn:
    """Local worker pool persisting every dispatch attempt and pool state on disk."""

    def __init__(
        self,
        pool_dir: Path | str | None = None,
        max_slots_per_round: int = 4,
        tenant_ceilings: dict[str, int] | None = None,
    ) -> None:
        if max_slots_per_round <= 0:
            raise ValueError("max_slots_per_round must be positive")
        self.pool_dir = Path(pool_dir) if pool_dir is not None else None
        self.max_slots_per_round = max_slots_per_round
        self.tenant_ceilings = dict(tenant_ceilings) if tenant_ceilings is not None else {}
        self.current_round_id = self.seq = self.round_slots_used = 0
        self.peak_round_slots = self.overflow_events = self.quota_breach_events = 0
        self.round_slot_counts: dict[int, int] = {}
        self.tenant_units_attempted: dict[str, int] = {}
        self.tenant_units_accepted: dict[str, int] = {}
        self.dispatched_job_ids: list[str] = []
        self._receipts: list[PoolReceipt] = []
        if self.pool_dir is not None:
            self.pool_dir.mkdir(parents=True, exist_ok=True)
            self._load_existing_state()

    def _load_existing_state(self) -> None:
        state_path = self.pool_dir / "pool_state.json" if self.pool_dir else None
        if state_path is None or not state_path.exists():
            return
        raw = json.loads(state_path.read_text(encoding="utf-8"))
        self.current_round_id = int(raw.get("current_round_id", 0))
        self.seq = int(raw.get("seq", 0))
        self.peak_round_slots = int(raw.get("peak_round_slots", 0))
        self.overflow_events = int(raw.get("overflow_events", 0))
        self.quota_breach_events = int(raw.get("quota_breach_events", 0))
        self.round_slot_counts = {int(k): int(v) for k, v in raw.get("round_slot_counts", {}).items()}
        self.tenant_units_attempted = {str(k): int(v) for k, v in raw.get("tenant_units_attempted", {}).items()}
        self.tenant_units_accepted = {str(k): int(v) for k, v in raw.get("tenant_units_accepted", {}).items()}
        self.dispatched_job_ids = [str(j) for j in raw.get("dispatched_job_ids", [])]
        if not self.tenant_ceilings and isinstance(raw.get("tenant_ceilings"), dict):
            self.tenant_ceilings = {str(k): int(v) for k, v in raw["tenant_ceilings"].items()}

    def begin_round(self, round_id: int | None = None) -> int:
        if round_id is not None and round_id <= 0:
            raise ValueError("round_id must be positive")
        self.current_round_id = (self.current_round_id + 1) if round_id is None else round_id
        self.round_slots_used = self.round_slot_counts.get(self.current_round_id, 0)
        return self.current_round_id

    def dispatch_job(self, job: ComputeJob, round_id: int | None = None) -> PoolReceipt:
        job.validate()
        if round_id is not None and round_id != self.current_round_id:
            self.begin_round(round_id)
        elif self.current_round_id == 0:
            self.begin_round(1)
        rid = self.current_round_id
        self.seq += 1
        self.round_slots_used += 1
        self.round_slot_counts[rid] = self.round_slots_used
        self.peak_round_slots = max(self.peak_round_slots, self.round_slots_used)
        self.tenant_units_attempted[job.tenant_id] = self.tenant_units_attempted.get(job.tenant_id, 0) + job.cost_units
        prev_acc = self.tenant_units_accepted.get(job.tenant_id, 0)
        ceiling = self.tenant_ceilings.get(job.tenant_id)
        reasons: list[str] = []
        if self.round_slots_used > self.max_slots_per_round:
            self.overflow_events += 1
            reasons.append("worker_slot_overflow")
        if ceiling is not None and prev_acc + job.cost_units > ceiling:
            self.quota_breach_events += 1
            reasons.append("quota_ceiling_breach")
        accepted = not reasons
        if accepted:
            self.tenant_units_accepted[job.tenant_id] = prev_acc + job.cost_units
        self.dispatched_job_ids.append(job.job_id)
        receipt = PoolReceipt(
            rid, self.seq, job.job_id, job.tenant_id, job.cost_units, accepted,
            "accepted" if accepted else ",".join(reasons), self.round_slots_used,
            self.tenant_units_attempted[job.tenant_id],
        )
        self._receipts.append(receipt)
        if self.pool_dir is not None:
            with (self.pool_dir / "dispatches.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(receipt.to_dict(), sort_keys=True) + "\n")
            (self.pool_dir / "pool_state.json").write_text(json.dumps(self.snapshot(), indent=2, sort_keys=True), encoding="utf-8")
        return receipt

    def end_round(self, round_id: int | None = None) -> dict[str, object]:
        rid = round_id if round_id is not None else self.current_round_id
        if self.pool_dir is not None:
            (self.pool_dir / "pool_state.json").write_text(json.dumps(self.snapshot(), indent=2, sort_keys=True), encoding="utf-8")
        return {"round_id": rid, "slots_used": self.round_slot_counts.get(rid, 0), "overflow_events": self.overflow_events, "quota_breach_events": self.quota_breach_events}

    def snapshot(self) -> dict[str, object]:
        return {
            "current_round_id": self.current_round_id, "seq": self.seq,
            "max_slots_per_round": self.max_slots_per_round, "round_slots_used": self.round_slots_used,
            "peak_round_slots": self.peak_round_slots, "overflow_events": self.overflow_events,
            "quota_breach_events": self.quota_breach_events,
            "round_slot_counts": {str(k): v for k, v in sorted(self.round_slot_counts.items())},
            "tenant_ceilings": dict(sorted(self.tenant_ceilings.items())),
            "tenant_units_attempted": dict(sorted(self.tenant_units_attempted.items())),
            "tenant_units_accepted": dict(sorted(self.tenant_units_accepted.items())),
            "dispatched_job_ids": list(self.dispatched_job_ids), "total_dispatches": len(self.dispatched_job_ids),
        }
