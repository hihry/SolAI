"""Immutable-ceiling quota ledger for multi-tenant compute budgets."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ChargeRecord:
    seq: int
    tenant_id: str
    cost_units: int
    remaining_after: int
    job_id: str | None = None


@dataclass
class TenantLease:
    tenant_id: str
    budget_units: int
    consumed_units: int = 0

    @property
    def remaining(self) -> int:
        return max(0, self.budget_units - self.consumed_units)

    @property
    def is_exhausted(self) -> bool:
        return self.remaining == 0


class QuotaLedger:
    def __init__(self) -> None:
        self._leases: dict[str, TenantLease] = {}
        self._initial_budgets: dict[str, int] = {}
        self._audit: list[ChargeRecord] = []

    def register_tenant(self, tenant_id: str, budget_units: int) -> None:
        if not tenant_id.strip():
            raise ValueError("tenant_id must be non-empty")
        if budget_units < 0:
            raise ValueError("budget_units cannot be negative")
        if tenant_id in self._leases:
            raise ValueError(f"tenant {tenant_id} already registered")
        self._leases[tenant_id] = TenantLease(tenant_id=tenant_id, budget_units=budget_units)
        self._initial_budgets[tenant_id] = budget_units

    def remaining_for(self, tenant_id: str) -> int:
        lease = self._leases.get(tenant_id)
        if lease is None:
            raise KeyError(f"unregistered tenant: {tenant_id}")
        return lease.remaining

    def can_afford(self, tenant_id: str, cost_units: int) -> bool:
        lease = self._leases.get(tenant_id)
        return lease is not None and cost_units > 0 and lease.remaining >= cost_units

    def charge(self, tenant_id: str, cost_units: int, job_id: str | None = None) -> int:
        if not self.can_afford(tenant_id, cost_units):
            raise RuntimeError(f"quota exceeded for tenant {tenant_id}")
        lease = self._leases[tenant_id]
        lease.consumed_units += cost_units
        self._audit.append(ChargeRecord(len(self._audit) + 1, tenant_id, cost_units, lease.remaining, job_id))
        return lease.remaining

    def audit_log(self) -> list[dict[str, object]]:
        return [asdict(entry) for entry in self._audit]

    def verify_invariants(self) -> bool:
        return all(
            l.budget_units == self._initial_budgets.get(tid) and 0 <= l.consumed_units <= l.budget_units
            for tid, l in self._leases.items()
        )

    def restore_consumed(self, consumed_by_tenant: dict[str, int]) -> None:
        for tid, consumed in consumed_by_tenant.items():
            lease = self._leases.get(tid)
            if lease is None:
                raise KeyError(f"unregistered tenant in state: {tid}")
            if consumed < 0 or consumed > lease.budget_units:
                raise RuntimeError(f"invalid consumed units {consumed} for tenant {tid}")
            lease.consumed_units = int(consumed)

    def snapshot(self) -> dict[str, dict[str, int]]:
        return {
            tid: {"budget": l.budget_units, "consumed": l.consumed_units, "remaining": l.remaining}
            for tid, l in sorted(self._leases.items())
        }
