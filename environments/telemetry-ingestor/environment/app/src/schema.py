"""Event schema validation and summary aggregation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


VALID_LEVELS = frozenset({"DEBUG", "INFO", "WARN", "ERROR"})


@dataclass(frozen=True)
class TelemetryEvent:
    event_id: str
    service: str
    level: str
    latency_ms: float
    payload: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if not self.event_id or not self.event_id.strip():
            raise ValueError("event_id must be non-empty")
        if not self.service or "/" in self.service:
            raise ValueError("service name must be a flat identifier")
        if self.level not in VALID_LEVELS:
            raise ValueError(f"unsupported level: {self.level}")
        if self.latency_ms < 0:
            raise ValueError("latency_ms must be non-negative")

    def to_record(self) -> dict[str, Any]:
        self.validate()
        return {
            "event_id": self.event_id,
            "service": self.service,
            "level": self.level,
            "latency_ms": round(self.latency_ms, 3),
            "payload": dict(self.payload),
        }


@dataclass
class BatchSummary:
    attempted: int = 0
    flushed: int = 0
    deferred: int = 0
    mean_latency_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempted": self.attempted,
            "flushed": self.flushed,
            "deferred": self.deferred,
            "mean_latency_ms": round(self.mean_latency_ms, 3),
        }


def compute_service_rollup(events: list[TelemetryEvent]) -> dict[str, dict[str, float]]:
    grouped: dict[str, list[float]] = {}
    for ev in events:
        ev.validate()
        grouped.setdefault(ev.service, []).append(ev.latency_ms)
    rollup: dict[str, dict[str, float]] = {}
    for svc, samples in sorted(grouped.items()):
        ordered = sorted(samples)
        p95_idx = min(len(ordered) - 1, int(len(ordered) * 0.95))
        rollup[svc] = {
            "count": float(len(ordered)),
            "avg_ms": round(sum(ordered) / len(ordered), 3),
            "p95_ms": round(ordered[p95_idx], 3),
        }
    return rollup
