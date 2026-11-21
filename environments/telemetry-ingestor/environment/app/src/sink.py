"""Rate-governed local sink abstraction and token bucket limiter."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .schema import TelemetryEvent


@dataclass
class TokenBucket:
    capacity: int
    tokens: float
    refill_per_tick: float

    def __post_init__(self) -> None:
        if self.capacity <= 0:
            raise ValueError("capacity must be positive")
        if self.refill_per_tick < 0:
            raise ValueError("refill_per_tick must be non-negative")
        self.tokens = min(float(self.capacity), max(0.0, float(self.tokens)))

    def advance(self, ticks: float = 1.0) -> None:
        if ticks > 0:
            self.tokens = min(float(self.capacity), self.tokens + ticks * self.refill_per_tick)

    def try_acquire(self, cost: int = 1) -> bool:
        if cost <= 0:
            return True
        if self.tokens >= cost:
            self.tokens -= cost
            return True
        return False


class LocalJournalSink:
    def __init__(self, journal_path: Path, per_call_ceiling: int = 25) -> None:
        self.journal_path = Path(journal_path)
        self.per_call_ceiling = per_call_ceiling
        self.journal_path.parent.mkdir(parents=True, exist_ok=True)

    def write_batch(self, events: list[TelemetryEvent]) -> list[str]:
        if len(events) > self.per_call_ceiling:
            raise RuntimeError("sink batch exceeds per_call_ceiling")
        accepted: list[str] = []
        with self.journal_path.open("a", encoding="utf-8") as handle:
            for ev in events:
                handle.write(json.dumps(ev.to_record(), sort_keys=True) + "\n")
                accepted.append(ev.event_id)
        return accepted
