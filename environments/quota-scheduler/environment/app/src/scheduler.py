"""Deficit Round Robin scheduler over tenant queues."""

from __future__ import annotations

from collections import deque

from .jobs import ComputeJob, TenantQueue
from .ledger import QuotaLedger
from .metrics import UtilizationTracker
from .standin import WorkerPoolStandIn


class FairScheduler:
    def __init__(
        self,
        ledger: QuotaLedger,
        worker_slots: int = 4,
        tracker: UtilizationTracker | None = None,
        worker_pool: WorkerPoolStandIn | None = None,
    ) -> None:
        if worker_slots <= 0:
            raise ValueError("worker_slots must be positive")
        self.ledger = ledger
        self.worker_slots = worker_slots
        self.tracker = tracker if tracker is not None else UtilizationTracker()
        self.worker_pool = worker_pool
        self.queues: dict[str, TenantQueue] = {}
        self.active_order: deque[str] = deque()
        self._round_counter = 0

    def ensure_tenant(self, tenant_id: str, quantum: int, budget_units: int) -> None:
        if tenant_id not in self.queues:
            self.queues[tenant_id] = TenantQueue(tenant_id=tenant_id, quantum=quantum)
            self.ledger.register_tenant(tenant_id=tenant_id, budget_units=budget_units)

    def submit(self, job: ComputeJob) -> None:
        if job.tenant_id not in self.queues:
            raise KeyError(f"unregistered tenant: {job.tenant_id}")
        q = self.queues[job.tenant_id]
        was_empty = len(q) == 0
        q.push(job)
        if was_empty and job.tenant_id not in self.active_order:
            self.active_order.append(job.tenant_id)

    def backlog_summary(self) -> dict[str, int]:
        return {tid: len(q) for tid, q in sorted(self.queues.items())}

    def pending_tenants(self) -> list[str]:
        return [tid for tid in self.active_order if len(self.queues[tid]) > 0]

    def export_state(self) -> dict[str, object]:
        return {
            "round_counter": self._round_counter,
            "active_order": list(self.active_order),
            "consumed": {tid: data["consumed"] for tid, data in self.ledger.snapshot().items()},
            "queues": {tid: {"deficit": q.deficit, "items": q.items_snapshot()} for tid, q in self.queues.items()},
            "tracker": self.tracker.export_state(),
        }

    def restore_state(self, state: dict[str, object]) -> None:
        self._round_counter = int(state.get("round_counter", 0))
        self.ledger.restore_consumed({str(k): int(v) for k, v in state.get("consumed", {}).items()})
        queues_state = state.get("queues", {})
        for tid, q in self.queues.items():
            q._items.clear()
            q_state = queues_state.get(tid, {})
            q.deficit = int(q_state.get("deficit", 0))
            for item in q_state.get("items", []):
                q.push(ComputeJob.from_dict(item))
        self.active_order = deque(
            str(tid) for tid in state.get("active_order", []) if str(tid) in self.queues and len(self.queues[str(tid)]) > 0
        )
        tracker_state = state.get("tracker")
        if isinstance(tracker_state, dict):
            self.tracker.restore_state(tracker_state)
        else:
            self.tracker.restore_state({})

    def schedule_round(self) -> list[ComputeJob]:
        """Dispatch up to worker_slots jobs using Deficit Round Robin and QuotaLedger enforcement."""
        raise NotImplementedError("Deficit Round Robin scheduling round is not implemented yet")
