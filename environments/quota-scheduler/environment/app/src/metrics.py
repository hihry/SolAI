"""Fairness telemetry and tenant utilization accounting."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


def compute_jains_fairness_index(allocations: list[float]) -> float:
    """Compute Jain's fairness index in (0.0, 1.0] across active tenant allocations."""
    cleaned = [float(x) for x in allocations if x >= 0]
    if not cleaned:
        return 1.0
    total = sum(cleaned)
    if total == 0.0:
        return 1.0
    sum_sq = sum(x * x for x in cleaned)
    return round((total * total) / (len(cleaned) * sum_sq), 6)


@dataclass
class RoundTelemetry:
    round_index: int
    dispatched_jobs: int
    units_allocated: dict[str, int]
    fairness_index: float
    worker_slots: int = 0
    deferred: dict[str, str] = field(default_factory=dict)


class UtilizationTracker:
    def __init__(self) -> None:
        self._totals: dict[str, int] = {}
        self._rounds: list[RoundTelemetry] = []

    def record_round(
        self,
        units_by_tenant: dict[str, int],
        dispatched_jobs: int,
        worker_slots: int = 0,
        deferred: dict[str, str] | None = None,
    ) -> RoundTelemetry:
        for tid, units in units_by_tenant.items():
            if units < 0:
                raise ValueError("allocated units cannot be negative")
            self._totals[tid] = self._totals.get(tid, 0) + units
        fairness = compute_jains_fairness_index(list(self._totals.values()))
        entry = RoundTelemetry(
            len(self._rounds) + 1, dispatched_jobs, dict(units_by_tenant),
            fairness, worker_slots, dict(deferred) if deferred else {},
        )
        self._rounds.append(entry)
        return entry

    def cumulative_units(self) -> dict[str, int]:
        return dict(sorted(self._totals.items()))

    def latest_fairness(self) -> float:
        return self._rounds[-1].fairness_index if self._rounds else 1.0

    def tenant_share(self, tenant_id: str) -> float:
        total = sum(self._totals.values())
        return round(self._totals.get(tenant_id, 0) / total, 6) if total > 0 else 0.0

    def history(self) -> list[dict[str, object]]:
        return [asdict(entry) for entry in self._rounds]

    def summary(self) -> dict[str, object]:
        return {"rounds": len(self._rounds), "cumulative_units": self.cumulative_units(), "latest_fairness": self.latest_fairness()}

    def export_state(self) -> dict[str, object]:
        return {
            "totals": dict(sorted(self._totals.items())),
            "rounds": self.history(),
        }

    def restore_state(self, state: dict[str, object]) -> None:
        raw_totals = state.get("totals", {})
        if not isinstance(raw_totals, dict):
            raise ValueError("tracker totals must be a mapping")
        restored_totals: dict[str, int] = {}
        for tid, units in raw_totals.items():
            val = int(units)
            if val < 0:
                raise ValueError("allocated units cannot be negative")
            restored_totals[str(tid)] = val
        raw_rounds = state.get("rounds", [])
        if not isinstance(raw_rounds, list):
            raise ValueError("tracker rounds must be a list")
        restored_rounds: list[RoundTelemetry] = []
        for entry in raw_rounds:
            restored_rounds.append(
                RoundTelemetry(
                    round_index=int(entry["round_index"]),
                    dispatched_jobs=int(entry["dispatched_jobs"]),
                    units_allocated={str(k): int(v) for k, v in dict(entry.get("units_allocated", {})).items()},
                    fairness_index=float(entry["fairness_index"]),
                    worker_slots=int(entry.get("worker_slots", 0)),
                    deferred={str(k): str(v) for k, v in dict(entry.get("deferred", {})).items()},
                )
            )
        self._totals = restored_totals
        self._rounds = restored_rounds
