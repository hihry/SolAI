"""Scoped registry catalog and transitive dependency resolver."""

from __future__ import annotations

from dataclasses import dataclass, field

from .lockfile import Lockfile, compute_sha256
from .semver import SemVer


@dataclass(frozen=True)
class ReleaseMetadata:
    name: str
    version: SemVer
    registry_id: str
    expected_sha256: str
    artifact_bytes: bytes
    requires: dict[str, str] = field(default_factory=dict)

    def verify_digest(self) -> bool:
        return compute_sha256(self.artifact_bytes) == self.expected_sha256


class RegistryCatalog:
    def __init__(self, scope_bindings: dict[str, str]) -> None:
        self.scope_bindings = dict(scope_bindings)
        self._releases: dict[tuple[str, str], list[ReleaseMetadata]] = {}

    def publish(self, release: ReleaseMetadata) -> None:
        key = (release.registry_id, release.name)
        self._releases.setdefault(key, []).append(release)

    def allowed_registry_for(self, package_name: str, default_registry: str = "public") -> str:
        if "/" in package_name:
            scope = package_name.split("/", 1)[0]
            if scope in self.scope_bindings:
                return self.scope_bindings[scope]
        return default_registry

    def list_releases(self, registry_id: str, package_name: str) -> list[ReleaseMetadata]:
        return list(self._releases.get((registry_id, package_name), ()))


class DependencyResolver:
    def __init__(self, catalog: RegistryCatalog, default_registry: str = "public") -> None:
        self.catalog = catalog
        self.default_registry = default_registry

    def resolve_lockfile(self, root_requirements: dict[str, str]) -> Lockfile:
        """Resolve transitive requirements using pinned scope bindings and digest verification."""
        raise NotImplementedError("Transitive scoped lockfile resolution is not implemented yet")
