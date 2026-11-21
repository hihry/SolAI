"""Lockfile representation, SHA-256 verification, and integrity checks."""
from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_HEX = frozenset("0123456789abcdef")


def compute_sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def verify_sha256(payload: bytes, expected_digest: str) -> bool:
    norm = expected_digest.strip().lower()
    return len(norm) == 64 and all(c in _HEX for c in norm) and hmac.compare_digest(compute_sha256(payload), norm)


@dataclass(frozen=True)
class LockedPackage:
    name: str
    version: str
    registry_id: str
    sha256: str
    dependencies: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "version": self.version, "registry_id": self.registry_id,
                "sha256": self.sha256, "dependencies": list(self.dependencies)}


class Lockfile:
    def __init__(self, packages: list[LockedPackage]) -> None:
        self.packages = list(packages)

    def package_map(self) -> dict[str, LockedPackage]:
        return {pkg.name: pkg for pkg in self.packages}

    def to_json(self) -> str:
        return json.dumps({"lockfile_version": 1, "packages": [p.to_dict() for p in self.packages]}, indent=2, sort_keys=True)

    def save(self, path: Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.to_json() + "\n", encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "Lockfile":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls([LockedPackage(i["name"], i["version"], i["registry_id"], i["sha256"], tuple(i.get("dependencies", ())))
                    for i in raw.get("packages", [])])

    def verify_integrity(self, scope_bindings: dict[str, str], default_registry: str = "public") -> list[str]:
        violations, seen = [], {}
        for idx, pkg in enumerate(self.packages):
            if pkg.name in seen:
                violations.append(f"duplicate lockfile entry: {pkg.name}")
                continue
            seen[pkg.name] = idx
            d = pkg.sha256.strip().lower()
            if len(d) != 64 or not all(c in _HEX for c in d):
                violations.append(f"invalid sha256 digest for {pkg.name}: {pkg.sha256}")
            if pkg.name.startswith("@"):
                scope = pkg.name.split("/", 1)[0] if "/" in pkg.name else ""
                expected = scope_bindings.get(scope)
                if not scope or expected is None:
                    violations.append(f"unbound or malformed scope for {pkg.name}")
                elif pkg.registry_id != expected:
                    violations.append(f"scope violation for {pkg.name}: expected {expected}, got {pkg.registry_id}")
            elif pkg.registry_id != default_registry:
                violations.append(f"unexpected registry {pkg.registry_id} for unscoped package {pkg.name}")
            for dep in pkg.dependencies:
                if seen.get(dep, idx) >= idx:
                    violations.append(f"topological order violation: {pkg.name} precedes or misses {dep}")
        return violations
