"""Local directory and loopback HTTP registry stand-ins with JSONL audit logging."""
from __future__ import annotations

import json, threading, urllib.parse, urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError


@dataclass(frozen=True)
class RegistryAuditEvent:
    timestamp: str; registry_id: str; action: str; package_name: str; found: bool
    version: str | None = None; sha256: str | None = None; transport: str = "directory"


def append_audit_event(audit_log_path: Path, event: RegistryAuditEvent, lock: threading.Lock | None = None) -> None:
    audit_log_path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(asdict(event), sort_keys=True) + "\n"
    if lock is None:
        with audit_log_path.open("a", encoding="utf-8") as fh:
            fh.write(line)
    else:
        with lock, audit_log_path.open("a", encoding="utf-8") as fh:
            fh.write(line)


def read_audit_events(audit_log_path: Path) -> list[RegistryAuditEvent]:
    if not audit_log_path.exists():
        return []
    return [RegistryAuditEvent(**json.loads(ln)) for ln in audit_log_path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class LocalDirectoryRegistryStandIn:
    def __init__(self, registry_id: str, root_dir: Path, audit_log_path: Path) -> None:
        self.registry_id, self.registry_dir = registry_id, Path(root_dir) / registry_id
        self.audit_log_path, self._lock = Path(audit_log_path), threading.Lock()

    def _load_releases(self) -> list[dict[str, Any]]:
        idx = self.registry_dir / "index.json"
        return list(json.loads(idx.read_text(encoding="utf-8")).get("releases", [])) if idx.exists() else []

    def _log(self, action: str, pkg: str, found: bool, ver: str | None = None, sha: str | None = None, transport: str = "directory") -> None:
        append_audit_event(self.audit_log_path, RegistryAuditEvent(_now(), self.registry_id, action, pkg, found, ver, sha, transport), self._lock)

    def list_releases(self, package_name: str, transport: str = "directory") -> list[dict[str, Any]]:
        matches = [r for r in self._load_releases() if r.get("name") == package_name]
        self._log("list_releases", package_name, bool(matches), ",".join(str(r["version"]) for r in matches) if matches else None, transport=transport)
        return matches

    def fetch_artifact(self, package_name: str, version: str, transport: str = "directory") -> bytes | None:
        entry = next((r for r in self._load_releases() if r.get("name") == package_name and r.get("version") == version), None)
        payload: bytes | None = None
        if entry is not None:
            if rel := entry.get("artifact_file"):
                art_root = (self.registry_dir / "artifacts").resolve()
                art_path = (art_root / rel).resolve()
                if art_path.is_file() and art_root in art_path.parents:
                    payload = art_path.read_bytes()
            elif "artifact_content" in entry:
                payload = str(entry["artifact_content"]).encode("utf-8")
        self._log("fetch_artifact", package_name, payload is not None, version, entry.get("sha256") if entry else None, transport)
        return payload


class LocalHttpRegistryStandIn:
    def __init__(self, standin: LocalDirectoryRegistryStandIn) -> None:
        self.standin, self._server, self._thread = standin, None, None

    @property
    def base_url(self) -> str:
        if self._server is None:
            raise RuntimeError("HTTP registry stand-in is not started")
        return f"http://{self._server.server_address[0]}:{self._server.server_address[1]}"

    def start(self) -> "LocalHttpRegistryStandIn":
        if self._server is not None:
            return self
        st = self.standin

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt: str, *args: Any) -> None:
                return

            def do_GET(self) -> None:  # noqa: N802
                p = [x for x in urllib.parse.urlsplit(self.path).path.split("/") if x]
                if len(p) == 5 and p[:4] == ["v1", "registries", st.registry_id, "packages"]:
                    self._reply(200, "application/json", json.dumps({"releases": st.list_releases(urllib.parse.unquote(p[4]), "http")}).encode("utf-8"))
                elif len(p) == 6 and p[:4] == ["v1", "registries", st.registry_id, "artifacts"]:
                    blob = st.fetch_artifact(urllib.parse.unquote(p[4]), urllib.parse.unquote(p[5]), "http")
                    self._reply(200 if blob is not None else 404, "application/octet-stream", blob or b"")
                else:
                    self._reply(404, "text/plain", b"")

            def _reply(self, code: int, ctype: str, body: bytes) -> None:
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if body:
                    self.wfile.write(body)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown(); self._server.server_close(); self._server = None
        if self._thread is not None:
            self._thread.join(timeout=2.0); self._thread = None

    def __enter__(self) -> "LocalHttpRegistryStandIn": return self.start()
    def __exit__(self, *_: object) -> None: self.stop()


class StandInRegistryCluster:
    def __init__(self, root_dir: Path, audit_log_path: Path, scope_bindings: dict[str, str],
                 registry_ids: Iterable[str] = ("internal-artifactory", "public"), use_http: bool = False) -> None:
        self.root_dir, self.audit_log_path = Path(root_dir), Path(audit_log_path)
        self.scope_bindings, self.use_http, self._lock = dict(scope_bindings), use_http, threading.Lock()
        all_regs = sorted(set(registry_ids) | set(scope_bindings.values()) | {"public"})
        self.registries = {r: LocalDirectoryRegistryStandIn(r, self.root_dir, self.audit_log_path) for r in all_regs}
        self._http_servers: dict[str, LocalHttpRegistryStandIn] = {}
        if use_http:
            self.start_http()

    @classmethod
    def seed_from_index(cls, index_path: Path, root_dir: Path, audit_log_path: Path, use_http: bool = False) -> "StandInRegistryCluster":
        raw = json.loads(Path(index_path).read_text(encoding="utf-8"))
        bindings = dict(raw.get("scope_bindings", {}))
        by_reg: dict[str, list[dict[str, Any]]] = {r: [] for r in {"internal-artifactory", "public", *bindings.values()}}
        for item in raw.get("releases", []):
            reg_id = item["registry_id"]
            art_dir = Path(root_dir) / reg_id / "artifacts"; art_dir.mkdir(parents=True, exist_ok=True)
            safe = f"{item['name'].replace('@', '').replace('/', '__')}-{item['version']}.bin"
            (art_dir / safe).write_bytes(str(item["artifact_content"]).encode("utf-8"))
            by_reg.setdefault(reg_id, []).append({**item, "artifact_file": safe})
        for reg_id, entries in by_reg.items():
            (Path(root_dir) / reg_id / "artifacts").mkdir(parents=True, exist_ok=True)
            (Path(root_dir) / reg_id / "index.json").write_text(json.dumps({"registry_id": reg_id, "releases": entries}, indent=2) + "\n", encoding="utf-8")
        return cls(root_dir, audit_log_path, bindings, by_reg.keys(), use_http=use_http)

    def start_http(self) -> None:
        for r, st in self.registries.items():
            self._http_servers.setdefault(r, LocalHttpRegistryStandIn(st).start())

    def close(self) -> None:
        for srv in self._http_servers.values(): srv.stop()
        self._http_servers.clear()

    def __enter__(self) -> "StandInRegistryCluster":
        if self.use_http: self.start_http()
        return self

    def __exit__(self, *_: object) -> None: self.close()

    def _http_get(self, srv: LocalHttpRegistryStandIn, path: str) -> bytes | None:
        try:
            with urllib.request.urlopen(f"{srv.base_url}{path}", timeout=5.0) as resp: return resp.read()
        except HTTPError as exc:
            if exc.code == 404: return None
            raise

    def list_releases(self, registry_id: str, package_name: str) -> list[dict[str, Any]]:
        if registry_id not in self.registries:
            append_audit_event(self.audit_log_path, RegistryAuditEvent(_now(), registry_id, "list_releases", package_name, False), self._lock)
            return []
        if srv := self._http_servers.get(registry_id):
            data = self._http_get(srv, f"/v1/registries/{registry_id}/packages/{urllib.parse.quote(package_name, safe='')}")
            return list(json.loads(data.decode("utf-8")).get("releases", [])) if data is not None else []
        return self.registries[registry_id].list_releases(package_name)

    def fetch_artifact(self, registry_id: str, package_name: str, version: str) -> bytes | None:
        if registry_id not in self.registries:
            append_audit_event(self.audit_log_path, RegistryAuditEvent(_now(), registry_id, "fetch_artifact", package_name, False, version=version), self._lock)
            return None
        if srv := self._http_servers.get(registry_id):
            return self._http_get(srv, f"/v1/registries/{registry_id}/artifacts/{urllib.parse.quote(package_name, safe='')}/{urllib.parse.quote(version, safe='')}")
        return self.registries[registry_id].fetch_artifact(package_name, version)
