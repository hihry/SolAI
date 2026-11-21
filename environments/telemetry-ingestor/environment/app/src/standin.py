"""Recording local downstream telemetry collector stand-in."""

from __future__ import annotations

import argparse
import json
import signal
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


class CollectorState:
    def __init__(self, audit_log_path: Path, accepted_log_path: Path, max_batch_size: int = 25, max_requests: int = 20, max_events: int = 100, window_sec: float = 5.0, retry_after_sec: float = 0.2) -> None:
        self.audit_log_path, self.accepted_log_path = Path(audit_log_path), Path(accepted_log_path)
        self.audit_log_path.parent.mkdir(parents=True, exist_ok=True)
        self.accepted_log_path.parent.mkdir(parents=True, exist_ok=True)
        self.max_batch_size, self.max_requests, self.max_events = max_batch_size, max_requests, max_events
        self.window_sec, self.retry_after_sec = float(window_sec), float(retry_after_sec)
        self._lock = threading.Lock()
        self._window: deque[tuple[float, int]] = deque()
        self._stats = {"requests_total": 0, "accepted_requests": 0, "throttled_requests": 0, "rejected_requests": 0, "accepted_events": 0}

    def _append_jsonl(self, path: Path, row: dict[str, Any]) -> None:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True) + "\n")

    def handle_batch(self, payload: dict[str, Any]) -> tuple[int, dict[str, Any], dict[str, str]]:
        events = payload.get("events")
        if not isinstance(events, list) or not all(isinstance(ev, dict) and isinstance(ev.get("event_id"), str) for ev in events):
            with self._lock:
                self._stats["requests_total"] += 1
                self._stats["rejected_requests"] += 1
                self._append_jsonl(self.audit_log_path, {"ts": time.time(), "status": 400, "batch_size": 0, "event_ids": [], "reason": "invalid_payload"})
            return 400, {"error": "invalid_payload"}, {}
        event_ids = [ev["event_id"] for ev in events]
        services = sorted({str(ev.get("service", "")) for ev in events})
        now = time.time()
        with self._lock:
            self._stats["requests_total"] += 1
            if len(events) > self.max_batch_size:
                self._stats["rejected_requests"] += 1
                self._append_jsonl(self.audit_log_path, {"ts": now, "status": 413, "batch_size": len(events), "event_ids": event_ids, "services": services, "reason": "batch_too_large"})
                return 413, {"error": "batch_too_large", "max_batch_size": self.max_batch_size}, {}
            cutoff = now - self.window_sec
            while self._window and self._window[0][0] < cutoff:
                self._window.popleft()
            win_evs = sum(cnt for _, cnt in self._window)
            if events and (len(self._window) + 1 > self.max_requests or win_evs + len(events) > self.max_events):
                self._stats["throttled_requests"] += 1
                self._append_jsonl(self.audit_log_path, {"ts": now, "status": 429, "batch_size": len(events), "event_ids": event_ids, "services": services, "reason": "rate_limited"})
                return 429, {"error": "rate_limited", "retry_after_sec": self.retry_after_sec}, {"Retry-After": str(self.retry_after_sec)}
            if events:
                self._window.append((now, len(events)))
            self._stats["accepted_requests"] += 1
            self._stats["accepted_events"] += len(events)
            for ev in events:
                self._append_jsonl(self.accepted_log_path, {**ev, "received_ts": now})
            self._append_jsonl(self.audit_log_path, {"ts": now, "status": 200, "batch_size": len(events), "event_ids": event_ids, "services": services, "reason": "ok"})
            return 200, {"accepted": event_ids, "count": len(events)}, {}

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {**self._stats, "limits": {"max_batch_size": self.max_batch_size, "max_requests": self.max_requests, "max_events": self.max_events, "window_sec": self.window_sec, "retry_after_sec": self.retry_after_sec}}

    def reset(self, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._lock:
            self._window.clear()
            self._stats = {"requests_total": 0, "accepted_requests": 0, "throttled_requests": 0, "rejected_requests": 0, "accepted_events": 0}
            for key in ("max_batch_size", "max_requests", "max_events"):
                if overrides and key in overrides:
                    setattr(self, key, int(overrides[key]))
            for key in ("window_sec", "retry_after_sec"):
                if overrides and key in overrides:
                    setattr(self, key, float(overrides[key]))
        return self.stats()


class LocalCollectorStandIn:
    def __init__(self, state: CollectorState, host: str = "127.0.0.1", port: int = 0) -> None:
        self.state = state
        class Handler(BaseHTTPRequestHandler):
            def _send(self, status: int, body: dict[str, Any], headers: dict[str, str] | None = None) -> None:
                raw = json.dumps(body, sort_keys=True).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(raw)
            def do_GET(self) -> None:  # noqa: N802
                self._send(200, state.stats()) if self.path == "/v1/stats" else self._send(404, {"error": "not_found"})
            def do_POST(self) -> None:  # noqa: N802
                try:
                    n = int(self.headers.get("Content-Length", "0"))
                    data = json.loads(self.rfile.read(n).decode("utf-8")) if n > 0 else {}
                except (ValueError, UnicodeDecodeError):
                    return self._send(400, {"error": "invalid_json"})
                if self.path == "/v1/telemetry/batch":
                    status, body, hdrs = state.handle_batch(data)
                    self._send(status, body, hdrs)
                elif self.path == "/v1/reset":
                    self._send(200, state.reset(data))
                else:
                    self._send(404, {"error": "not_found"})
            def log_message(self, format: str, *args: object) -> None:  # noqa: A002
                return
        self._server = ThreadingHTTPServer((host, port), Handler)
        self.host, self.port = self._server.server_address[0], int(self._server.server_address[1])
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def start(self) -> None:
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2.0)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="telemetry-collector-standin")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=0)
    p.add_argument("--port-file", type=Path, default=None)
    p.add_argument("--audit-log", type=Path, required=True)
    p.add_argument("--accepted-log", type=Path, required=True)
    p.add_argument("--max-batch-size", type=int, default=25)
    p.add_argument("--max-requests", type=int, default=20)
    p.add_argument("--max-events", type=int, default=100)
    p.add_argument("--window-sec", type=float, default=5.0)
    p.add_argument("--retry-after", type=float, default=0.2)
    a = p.parse_args(argv)
    standin = LocalCollectorStandIn(CollectorState(a.audit_log, a.accepted_log, a.max_batch_size, a.max_requests, a.max_events, a.window_sec, a.retry_after), a.host, a.port)
    if a.port_file is not None:
        a.port_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = a.port_file.with_suffix(".tmp")
        tmp.write_text(str(standin.port), encoding="utf-8")
        tmp.replace(a.port_file)
    stop_ev = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop_ev.set())
    standin.start()
    try:
        stop_ev.wait()
    finally:
        standin.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
