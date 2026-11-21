"""CLI entrypoint for artifact-resolver."""
from __future__ import annotations
import argparse
import json
import os
import sys
from pathlib import Path

from .graph import CycleError
from .lockfile import Lockfile, compute_sha256
from .resolver import RegistryCatalog, ReleaseMetadata, ResolutionError
from .semver import SemVer
from .standin import StandInRegistryCluster


def load_catalog(index_path: Path, standin_dir: Path | None = None,
                 audit_log: Path | None = None, use_http: bool = False) -> RegistryCatalog:
    raw = json.loads(index_path.read_text(encoding="utf-8"))
    resolved_audit = audit_log or (Path(v) if (v := os.environ.get("ARTIFACT_RESOLVER_AUDIT_LOG")) else None)
    resolved_standin = standin_dir or (Path(v) if (v := os.environ.get("ARTIFACT_RESOLVER_STANDIN_DIR")) else None)
    if resolved_standin is not None:
        effective_audit = resolved_audit or (resolved_standin / "audit.jsonl")
        cluster = StandInRegistryCluster.seed_from_index(index_path, resolved_standin, effective_audit, use_http=use_http)
        return RegistryCatalog(raw.get("scope_bindings", {}), standin_cluster=cluster, audit_log_path=effective_audit)
    catalog = RegistryCatalog(raw.get("scope_bindings", {}), audit_log_path=resolved_audit)
    for item in raw.get("releases", []):
        blob = item["artifact_content"].encode("utf-8")
        catalog.publish(ReleaseMetadata(
            item["name"], SemVer.parse(item["version"]), item["registry_id"],
            item.get("sha256") or compute_sha256(blob), blob, item.get("requires", {}),
        ))
    return catalog


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="artifact-resolver")
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--standin-dir", type=Path, default=None)
    parser.add_argument("--audit-log", type=Path, default=None)
    parser.add_argument("--http-standin", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check-scope").add_argument("--package", required=True)
    sub.add_parser("verify-lock").add_argument("--lockfile", type=Path, required=True)
    lck = sub.add_parser("lock")
    lck.add_argument("--manifest", type=Path, required=True)
    lck.add_argument("--output", type=Path, required=True)

    args = parser.parse_args(argv)
    catalog = load_catalog(args.index, args.standin_dir, args.audit_log, args.http_standin)
    try:
        if args.command == "check-scope":
            print(json.dumps({"package": args.package, "registry_id": catalog.allowed_registry_for(args.package)}))
            return 0
        if args.command == "verify-lock":
            violations = Lockfile.load(args.lockfile).verify_integrity(catalog.scope_bindings)
            print(json.dumps({"valid": not violations, "violations": violations}))
            return 0 if not violations else 1
        if args.command == "lock":
            raise NotImplementedError("lock subcommand is not enabled yet")
        return 1
    except (NotImplementedError, ResolutionError, CycleError, ValueError) as exc:
        print(json.dumps({"error": type(exc).__name__, "detail": str(exc)}), file=sys.stderr)
        return 2
    finally:
        if catalog.standin_cluster is not None:
            catalog.standin_cluster.close()


if __name__ == "__main__":
    raise SystemExit(main())
