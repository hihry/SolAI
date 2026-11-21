"""Lockfile representation and SHA-256 verification helpers."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def compute_sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class LockedPackage:
    name: str
    version: str
    registry_id: str
    sha256: str
    dependencies: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "registry_id": self.registry_id,
            "sha256": self.sha256,
            "dependencies": list(self.dependencies),
        }


class Lockfile:
    def __init__(self, packages: list[LockedPackage]) -> None:
        self.packages = list(packages)

    def to_json(self) -> str:
        body = {
            "lockfile_version": 1,
            "packages": [pkg.to_dict() for pkg in self.packages],
        }
        return json.dumps(body, indent=2, sort_keys=True)

    def save(self, path: Path) -> None:
        Path(path).write_text(self.to_json() + "\n", encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "Lockfile":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        pkgs = [
            LockedPackage(
                name=item["name"],
                version=item["version"],
                registry_id=item["registry_id"],
                sha256=item["sha256"],
                dependencies=tuple(item.get("dependencies", ())),
            )
            for item in raw.get("packages", [])
        ]
        return cls(pkgs)
