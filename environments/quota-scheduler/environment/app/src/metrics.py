"""Fairness telemetry and tenant utilization accounting."""

from __future__ import annotations

from dataclasses import dataclass


def compute_jains_fairness_index(allocations: list[float]) -> float:
    """Compute Jain's fairness index in (0.0, 1.0] across active tenant allocations."""
    cleaned = [float(x) for x in allocations if x >= 0]
    if not cleaned:
        return 1.0
    total = sum(cleaned)
    if total == 0.0:
        return 1.0
    sum_sq = sum(x * x for x in cleaned)
    n = len(cleaned)
    return round((total * total) / (n * sum_sq), 6)


@dataclass
class RoundTelemetry:
    round_index: int
    dispatched_jobs: int
    units_allocated: dict[str, int]
    fairness_index: float


class UtilizationTracker:
    def __init__(self) -> None:
        self._totals: dict[str, int] = {}
        self._rounds: list[RoundTelemetry] = []

    def record_round(self, units_by_tenant: dict[str, int], dispatched_jobs: int) -> RoundTelemetry:
        for tid, units in units_by_tenant.items():
            if units < 0:
                raise ValueError("allocated units cannot be negative")
            self._totals[tid] = self._totals.get(tid, 0) + units
        fairness = compute_jains_fairness_index(list(self._totals.values()))
        entry = RoundTelemetry(
            round_index=len(self._rounds) + 1,
            dispatched_jobs=dispatched_jobs,
            units_allocated=dict(units_by_tenant),
            fairness_index=fairness,
        )
        self._rounds.append(entry)
        return entry

    def cumulative_units(self) -> dict[str, int]:
        return dict(sorted(self._totals.items()))

    def latest_fairness(self) -> float:
        if not self._rounds:
            return 1.0
        return self._rounds[-1].fairness_index
