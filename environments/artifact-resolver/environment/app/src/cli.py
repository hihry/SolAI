"""CLI entrypoint for artifact-resolver."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .lockfile import compute_sha256
from .resolver import DependencyResolver, RegistryCatalog, ReleaseMetadata
from .semver import SemVer


def load_catalog(index_path: Path) -> RegistryCatalog:
    raw = json.loads(index_path.read_text(encoding="utf-8"))
    catalog = RegistryCatalog(scope_bindings=raw.get("scope_bindings", {}))
    for item in raw.get("releases", []):
        blob = item["artifact_content"].encode("utf-8")
        digest = item.get("sha256") or compute_sha256(blob)
        catalog.publish(
            ReleaseMetadata(
                name=item["name"],
                version=SemVer.parse(item["version"]),
                registry_id=item["registry_id"],
                expected_sha256=digest,
                artifact_bytes=blob,
                requires=item.get("requires", {}),
            )
        )
    return catalog


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="artifact-resolver")
    parser.add_argument("--index", type=Path, required=True)
    sub = parser.add_subparsers(dest="command", required=True)

    chk = sub.add_parser("check-scope")
    chk.add_argument("--package", required=True)

    lck = sub.add_parser("lock")
    lck.add_argument("--manifest", type=Path, required=True)
    lck.add_argument("--output", type=Path, required=True)

    args = parser.parse_args(argv)
    catalog = load_catalog(args.index)
    if args.command == "check-scope":
        reg = catalog.allowed_registry_for(args.package)
        print(json.dumps({"package": args.package, "registry_id": reg}))
        return 0
    if args.command == "lock":
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        resolver = DependencyResolver(catalog)
        lockfile = resolver.resolve_lockfile(manifest.get("dependencies", {}))
        lockfile.save(args.output)
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
