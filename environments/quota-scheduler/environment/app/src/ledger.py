"""Immutable-ceiling quota ledger for multi-tenant compute budgets."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TenantLease:
    tenant_id: str
    budget_units: int
    consumed_units: int = 0

    @property
    def remaining(self) -> int:
        return max(0, self.budget_units - self.consumed_units)


class QuotaLedger:
    def __init__(self) -> None:
        self._leases: dict[str, TenantLease] = {}

    def register_tenant(self, tenant_id: str, budget_units: int) -> None:
        if budget_units < 0:
            raise ValueError("budget_units cannot be negative")
        self._leases[tenant_id] = TenantLease(tenant_id=tenant_id, budget_units=budget_units)

    def can_afford(self, tenant_id: str, cost_units: int) -> bool:
        lease = self._leases.get(tenant_id)
        if lease is None or cost_units <= 0:
            return False
        return lease.remaining >= cost_units

    def charge(self, tenant_id: str, cost_units: int) -> int:
        if not self.can_afford(tenant_id, cost_units):
            raise RuntimeError(f"quota exceeded for tenant {tenant_id}")
        lease = self._leases[tenant_id]
        lease.consumed_units += cost_units
        return lease.remaining

    def snapshot(self) -> dict[str, dict[str, int]]:
        return {
            tid: {
                "budget": lease.budget_units,
                "consumed": lease.consumed_units,
                "remaining": lease.remaining,
            }
            for tid, lease in sorted(self._leases.items())
        }
