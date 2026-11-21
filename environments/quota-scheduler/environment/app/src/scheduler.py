"""Deficit Round Robin scheduler over tenant queues."""

from __future__ import annotations

from collections import deque

from .jobs import ComputeJob, TenantQueue
from .ledger import QuotaLedger
from .metrics import UtilizationTracker


class FairScheduler:
    def __init__(
        self,
        ledger: QuotaLedger,
        worker_slots: int = 4,
        tracker: UtilizationTracker | None = None,
    ) -> None:
        if worker_slots <= 0:
            raise ValueError("worker_slots must be positive")
        self.ledger = ledger
        self.worker_slots = worker_slots
        self.tracker = tracker if tracker is not None else UtilizationTracker()
        self.queues: dict[str, TenantQueue] = {}
        self.active_order: deque[str] = deque()

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

    def schedule_round(self) -> list[ComputeJob]:
        """Dispatch up to worker_slots jobs using Deficit Round Robin and QuotaLedger enforcement."""
        raise NotImplementedError("Deficit Round Robin scheduling round is not implemented yet")
