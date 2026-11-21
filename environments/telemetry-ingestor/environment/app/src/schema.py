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


@dataclass(frozen=True)
class IngestorConfig:
    batch_size: int = 10
    max_retries: int = 4
    base_backoff_sec: float = 0.05
    max_backoff_sec: float = 0.25
    max_drain_attempts: int = 2

    def __post_init__(self) -> None:
        if self.batch_size <= 0:
            raise ValueError("batch_size must be positive")
        if self.max_retries <= 0:
            raise ValueError("max_retries must be positive")
        if self.base_backoff_sec < 0 or self.max_backoff_sec < self.base_backoff_sec:
            raise ValueError("invalid backoff bounds")
        if self.max_drain_attempts <= 0:
            raise ValueError("max_drain_attempts must be positive")


def compute_backoff_delay(attempt: int, base_sec: float = 0.05, max_sec: float = 0.25) -> float:
    if attempt < 0 or base_sec <= 0:
        return 0.0
    return min(max_sec, base_sec * (2 ** min(attempt, 10)))

