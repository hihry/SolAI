"""Scoped registry catalog and transitive dependency resolver."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .lockfile import Lockfile, compute_sha256, verify_sha256
from .semver import SemVer
from .standin import RegistryAuditEvent, StandInRegistryCluster, append_audit_event


class ResolutionError(RuntimeError):
    """Base error for dependency resolution failures."""


class ScopeViolationError(ResolutionError):
    """Raised when a scoped package violates registry binding policy."""


class DigestMismatchError(ResolutionError):
    """Raised when an artifact fails SHA-256 verification."""


class MissingPackageError(ResolutionError):
    """Raised when no compatible release exists in the pinned registry."""


@dataclass(frozen=True)
class ReleaseMetadata:
    name: str
    version: SemVer
    registry_id: str
    expected_sha256: str
    artifact_bytes: bytes
    requires: dict[str, str] = field(default_factory=dict)

    def verify_digest(self) -> bool:
        return verify_sha256(self.artifact_bytes, self.expected_sha256)


class RegistryCatalog:
    def __init__(self, scope_bindings: dict[str, str],
                 standin_cluster: StandInRegistryCluster | None = None,
                 audit_log_path: Path | None = None) -> None:
        self.scope_bindings, self.standin_cluster = dict(scope_bindings), standin_cluster
        self.audit_log_path = Path(audit_log_path) if audit_log_path is not None else None
        self._releases: dict[tuple[str, str], list[ReleaseMetadata]] = {}

    def publish(self, release: ReleaseMetadata) -> None:
        self._releases.setdefault((release.registry_id, release.name), []).append(release)

    def is_bound_scope(self, package_name: str) -> bool:
        return package_name.startswith("@") and "/" in package_name and package_name.split("/", 1)[0] in self.scope_bindings

    def allowed_registry_for(self, package_name: str, default_registry: str = "public") -> str:
        if "/" in package_name and (scope := package_name.split("/", 1)[0]) in self.scope_bindings:
            return self.scope_bindings[scope]
        return default_registry

    def list_releases(self, registry_id: str, package_name: str) -> list[ReleaseMetadata]:
        if self.standin_cluster is not None:
            releases: list[ReleaseMetadata] = []
            for item in self.standin_cluster.list_releases(registry_id, package_name):
                if (blob := self.standin_cluster.fetch_artifact(registry_id, package_name, item["version"])) is not None:
                    releases.append(ReleaseMetadata(
                        item["name"], SemVer.parse(item["version"]), item["registry_id"],
                        item.get("sha256") or compute_sha256(blob), blob, dict(item.get("requires", {})),
                    ))
            return releases
        releases = list(self._releases.get((registry_id, package_name), ()))
        if self.audit_log_path is not None:
            vers = ",".join(str(r.version) for r in releases) if releases else None
            append_audit_event(self.audit_log_path, RegistryAuditEvent(
                datetime.now(timezone.utc).isoformat(), registry_id, "list_releases", package_name, bool(releases), vers, transport="catalog"
            ))
        return releases


class DependencyResolver:
    def __init__(self, catalog: RegistryCatalog, default_registry: str = "public") -> None:
        self.catalog, self.default_registry = catalog, default_registry

    def resolve_lockfile(self, root_requirements: dict[str, str]) -> Lockfile:
        """Resolve transitive requirements using pinned scope bindings and digest verification."""
        raise NotImplementedError("Transitive scoped lockfile resolution is not implemented yet")
