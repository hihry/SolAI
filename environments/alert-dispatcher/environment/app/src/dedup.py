"""Priority-ordered incident deduplication window."""

from __future__ import annotations

import heapq
from dataclasses import dataclass

from .incidents import IncidentSignal


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

    def observe(self, signal: IncidentSignal) -> AggregatedIncident:
        signal.validate()
        fp = signal.fingerprint()
        existing = self._groups.get(fp)
        if existing is None:
            agg = AggregatedIncident(
                fingerprint=fp,
                subsystem=signal.subsystem,
                peak_severity=signal.severity,
                peak_rank=signal.rank,
                occurrences=1,
                latest_summary=signal.summary,
                runbook_slug=signal.runbook_slug,
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
        heap: list[tuple[int, int, str, AggregatedIncident]] = []
        for fp, item in self._groups.items():
            heapq.heappush(heap, (-item.peak_rank, -item.occurrences, fp, item))
        results: list[AggregatedIncident] = []
        while heap and len(results) < limit:
            _, _, _, item = heapq.heappop(heap)
            results.append(item)
        return results
