"""Local offline webhook/notification receiver stand-in."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import threading
import urllib.request
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

_URL_RE = re.compile(r"https?://[^\s<>\"'\)\]]+", re.IGNORECASE)
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


@dataclass(frozen=True)
class DeliveryRecord:
    delivery_id: str
    timestamp_utc: str
    channel: str
    transport: str
    content_type: str
    headers: dict[str, str]
    body: str
    extracted_urls: list[str]
    origins: list[str]
    byte_length: int
    sha256: str
    payload_path: str


class LocalWebhookStandIn:
    def __init__(self, state_dir: Path) -> None:
        self.state_dir = Path(state_dir)
        self.payloads_dir = self.state_dir / "payloads"
        self.ledger_path = self.state_dir / "deliveries.jsonl"
        self._lock = threading.Lock()
        self.payloads_dir.mkdir(parents=True, exist_ok=True)

    def deliver(
        self, channel: str, body: str, content_type: str = "text/plain",
        headers: dict[str, str] | None = None, transport: str = "local_spool",
    ) -> DeliveryRecord:
        did = uuid.uuid4().hex[:12]
        raw = body.encode("utf-8")
        urls = _URL_RE.findall(body)
        origins = sorted({f"{p.scheme.lower()}://{p.netloc.lower()}" for u in urls for p in (urlparse(u),) if p.scheme and p.netloc})
        safe_ch = re.sub(r"[^A-Za-z0-9._-]", "_", channel)[:48] or "channel"
        payload_file = self.payloads_dir / f"{did}_{safe_ch}.txt"
        record = DeliveryRecord(
            did, datetime.now(timezone.utc).isoformat(), channel, transport,
            content_type.split(";", 1)[0].strip().lower(),
            {str(k).lower(): str(v) for k, v in (headers or {}).items()},
            body, urls, origins, len(raw), hashlib.sha256(raw).hexdigest(), str(payload_file),
        )
        with self._lock:
            self.payloads_dir.mkdir(parents=True, exist_ok=True)
            payload_file.write_bytes(raw)
            with self.ledger_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(asdict(record), sort_keys=True) + "\n")
                handle.flush()
        return record

    def read_deliveries(self) -> list[dict[str, Any]]:
        if not self.ledger_path.exists():
            return []
        return [json.loads(line) for line in self.ledger_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def clear(self) -> None:
        with self._lock:
            if self.ledger_path.exists():
                self.ledger_path.unlink()
            for child in self.payloads_dir.glob("*"):
                if child.is_file():
                    child.unlink()


class LocalWebhookServer:
    def __init__(self, state_dir: Path, host: str = "127.0.0.1", port: int = 0) -> None:
        if host not in _LOOPBACK_HOSTS:
            raise ValueError(f"stand-in server only binds loopback hosts, got: {host}")
        self.standin = LocalWebhookStandIn(state_dir)
        standin = self.standin

        class _Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
                return

            def _reply(self, status: int, payload: dict[str, Any]) -> None:
                data = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self) -> None:
                if self.path == "/health":
                    self._reply(200, {"status": "ok", "deliveries": len(standin.read_deliveries())})
                    return
                self._reply(404, {"error": "not found"})

            def do_POST(self) -> None:
                raw_len = self.headers.get("Content-Length", "0").strip()
                if not (raw_len.isascii() and raw_len.isdigit()):
                    self._reply(400, {"error": "invalid Content-Length"})
                    return
                body = self.rfile.read(int(raw_len)).decode("utf-8", errors="replace")
                if self.path.startswith("/webhook/"):
                    channel = self.path[len("/webhook/"):].strip("/") or "default"
                elif self.path == "/notify":
                    channel = self.headers.get("X-Alert-Channel", "default")
                else:
                    self._reply(404, {"error": "unknown endpoint"})
                    return
                rec = standin.deliver(
                    channel=channel, body=body, content_type=self.headers.get("Content-Type", "text/plain"),
                    headers=dict(self.headers.items()), transport="local_http",
                )
                self._reply(202, {"status": "accepted", "delivery_id": rec.delivery_id, "channel": rec.channel})

        self._httpd = ThreadingHTTPServer((host, port), _Handler)
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        host, port = self._httpd.server_address[:2]
        return f"http://{host}:{port}"

    def __enter__(self) -> LocalWebhookServer:
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2.0)


def post_to_local_webhook(
    webhook_url: str, channel: str, body: str, content_type: str = "text/plain"
) -> dict[str, Any]:
    parsed = urlparse(webhook_url)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in _LOOPBACK_HOSTS:
        raise ValueError(f"only loopback webhook URLs are permitted offline: {webhook_url}")
    base = webhook_url.rstrip("/")
    target = base if ("/webhook/" in parsed.path or parsed.path == "/notify") else f"{base}/webhook/{channel}"
    req = urllib.request.Request(
        target, data=body.encode("utf-8"),
        headers={"Content-Type": content_type, "X-Alert-Channel": channel}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=5.0) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


if __name__ == "__main__":
    p = argparse.ArgumentParser(prog="alert-standin")
    p.add_argument("--state-dir", type=Path, required=True)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8089)
    ns = p.parse_args()
    with LocalWebhookServer(ns.state_dir, host=ns.host, port=ns.port) as srv:
        print(json.dumps({"listening": srv.url}), flush=True)
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pass
