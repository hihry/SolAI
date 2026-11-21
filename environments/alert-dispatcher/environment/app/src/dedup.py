"""Priority-ordered incident deduplication window."""

from __future__ import annotations

import heapq
from dataclasses import dataclass

from .incidents import SEVERITY_RANK, IncidentSignal


@dataclass
class AggregatedIncident:
    fingerprint: str
    subsystem: str
    peak_severity: str
    peak_rank: int
    occurrences: int
    latest_summary: str
    runbook_slug: str


class Deduplicator:
    def __init__(self) -> None:
        self._groups: dict[str, AggregatedIncident] = {}
        self._total_observed: int = 0

    @property
    def total_observed(self) -> int:
        return self._total_observed

    @property
    def group_count(self) -> int:
        return len(self._groups)

    def observe(self, signal: IncidentSignal) -> AggregatedIncident:
        signal.validate()
        self._total_observed += 1
        fp = signal.fingerprint()
        existing = self._groups.get(fp)
        if existing is None:
            agg = AggregatedIncident(
                fp, signal.subsystem, signal.severity, signal.rank, 1, signal.summary, signal.runbook_slug
            )
            self._groups[fp] = agg
            return agg
        existing.occurrences += 1
        existing.latest_summary = signal.summary
        if signal.rank > existing.peak_rank:
            existing.peak_rank = signal.rank
            existing.peak_severity = signal.severity
        return existing

    def top_incidents(self, limit: int = 20) -> list[AggregatedIncident]:
        if limit < 0:
            raise ValueError("limit must be non-negative")
        if limit == 0:
            return []
        heap: list[tuple[int, int, str, AggregatedIncident]] = []
        for fp, item in self._groups.items():
            heapq.heappush(heap, (-item.peak_rank, -item.occurrences, fp, item))
        results: list[AggregatedIncident] = []
        while heap and len(results) < limit:
            results.append(heapq.heappop(heap)[3])
        return results

    def severity_counts(self) -> dict[str, int]:
        counts = {sev: 0 for sev in SEVERITY_RANK}
        for item in self._groups.values():
            counts[item.peak_severity] = counts.get(item.peak_severity, 0) + 1
        return counts

    def subsystem_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in self._groups.values():
            counts[item.subsystem] = counts.get(item.subsystem, 0) + item.occurrences
        return dict(sorted(counts.items()))

    def clear(self) -> None:
        self._groups.clear()
        self._total_observed = 0
