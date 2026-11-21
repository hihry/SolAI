"""Compute job specification and tenant queue structures."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class ComputeJob:
    job_id: str
    tenant_id: str
    cost_units: int
    payload_ref: str
    priority_hint: int = 0

    def validate(self) -> None:
        if not self.job_id.strip() or not self.tenant_id.strip():
            raise ValueError("job_id and tenant_id must be non-empty")
        if self.cost_units <= 0:
            raise ValueError("cost_units must be positive")
        if not self.payload_ref.strip():
            raise ValueError("payload_ref must be non-empty")
        if not (-10 <= self.priority_hint <= 10):
            raise ValueError("priority_hint must be within [-10, 10]")

    def to_dict(self) -> dict[str, object]:
        return {
            "job_id": self.job_id, "tenant_id": self.tenant_id, "cost_units": self.cost_units,
            "payload_ref": self.payload_ref, "priority_hint": self.priority_hint,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> ComputeJob:
        return cls(
            str(data["job_id"]), str(data["tenant_id"]), int(data["cost_units"]),
            str(data["payload_ref"]), int(data.get("priority_hint", 0)),
        )


class TenantQueue:
    def __init__(self, tenant_id: str, quantum: int) -> None:
        if not tenant_id.strip():
            raise ValueError("tenant_id must be non-empty")
        if quantum <= 0:
            raise ValueError("quantum must be positive")
        self.tenant_id = tenant_id
        self.quantum = quantum
        self.deficit: int = 0
        self._items: deque[ComputeJob] = deque()

    def add_quantum(self) -> int:
        self.deficit += self.quantum
        return self.deficit

    def reset_if_empty(self) -> None:
        if not self._items:
            self.deficit = 0

    def push(self, job: ComputeJob) -> None:
        job.validate()
        if job.tenant_id != self.tenant_id:
            raise ValueError("tenant mismatch on queue push")
        self._items.append(job)

    def peek(self) -> ComputeJob | None:
        return self._items[0] if self._items else None

    def can_dispatch_head(self, remaining_budget: int) -> bool:
        head = self.peek()
        return head is not None and self.deficit >= head.cost_units and remaining_budget >= head.cost_units

    def defer_reason(self, remaining_budget: int) -> str | None:
        head = self.peek()
        if head is None:
            return "empty"
        if remaining_budget < head.cost_units:
            return "quota_exhausted"
        return "insufficient_deficit" if self.deficit < head.cost_units else None

    def pop(self) -> ComputeJob:
        job = self._items.popleft()
        self.reset_if_empty()
        return job

    def total_queued_cost(self) -> int:
        return sum(item.cost_units for item in self._items)

    def items_snapshot(self) -> list[dict[str, object]]:
        return [item.to_dict() for item in self._items]

    def __len__(self) -> int:
        return len(self._items)
