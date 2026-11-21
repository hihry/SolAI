"""Rate-governed local sink abstraction and token bucket limiter."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .schema import TelemetryEvent


class SinkThrottledError(RuntimeError):
    def __init__(self, message: str, status_code: int = 429, retry_after_sec: float = 0.2) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retry_after_sec = max(0.0, float(retry_after_sec))


class SinkRejectedError(RuntimeError):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


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
    def __init__(
        self,
        journal_path: Path,
        per_call_ceiling: int = 25,
        collector_url: str | None = None,
        timeout_sec: float = 2.0,
    ) -> None:
        if per_call_ceiling <= 0:
            raise ValueError("per_call_ceiling must be positive")
        self.journal_path = Path(journal_path)
        self.per_call_ceiling = per_call_ceiling
        raw_url = collector_url if collector_url is not None else os.environ.get("TELEMETRY_COLLECTOR_URL")
        self.collector_url = raw_url.rstrip("/") if raw_url else None
        self.timeout_sec = float(timeout_sec)
        self.journal_path.parent.mkdir(parents=True, exist_ok=True)

    def _post_collector(self, records: list[dict[str, object]]) -> None:
        assert self.collector_url is not None
        body = json.dumps({"events": records}, sort_keys=True).encode("utf-8")
        req = urllib.request.Request(
            f"{self.collector_url}/v1/telemetry/batch",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
                if resp.status >= 400:
                    raise SinkRejectedError(f"collector error status {resp.status}", status_code=resp.status)
        except urllib.error.HTTPError as exc:
            retry_hdr = exc.headers.get("Retry-After") if exc.headers else None
            _ = exc.read()
            if exc.code == 429:
                retry_sec = float(retry_hdr) if retry_hdr else 0.2
                raise SinkThrottledError(f"collector throttled batch ({exc.code})", status_code=429, retry_after_sec=retry_sec) from exc
            raise SinkRejectedError(f"collector rejected batch ({exc.code})", status_code=exc.code) from exc
        except urllib.error.URLError as exc:
            raise SinkRejectedError(f"collector unreachable: {exc.reason}", status_code=503) from exc

    def write_batch(self, events: list[TelemetryEvent]) -> list[str]:
        if len(events) > self.per_call_ceiling:
            raise RuntimeError("sink batch exceeds per_call_ceiling")
        if not events:
            return []
        records = [ev.to_record() for ev in events]
        if self.collector_url:
            self._post_collector(records)
        accepted: list[str] = []
        with self.journal_path.open("a", encoding="utf-8") as handle:
            for rec in records:
                handle.write(json.dumps(rec, sort_keys=True) + "\n")
                accepted.append(str(rec["event_id"]))
        return accepted
