"""CLI entrypoint for build-provenance."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .manifest import load_stage_chain
from .merkle import MerkleTree
from .pipeline import ProvenancePipeline
from .standin import LocalAttestationStandIn
from .verifier import AttestationLedger


def _resolve_ledger(ledger_arg: Path | None) -> AttestationLedger | None:
    if ledger_arg is not None:
        return AttestationLedger(ledger_arg)
    env_ledger = os.environ.get("PROVENANCE_LEDGER_PATH", "").strip()
    return AttestationLedger(Path(env_ledger)) if env_ledger else None


def _resolve_standin(standin_arg: Path | None) -> LocalAttestationStandIn | None:
    return LocalAttestationStandIn(standin_arg) if standin_arg is not None else LocalAttestationStandIn.from_env()


def _serialize_audit(audit: Any) -> dict[str, Any]:
    data = asdict(audit)
    data["reasons"] = list(audit.reasons)
    data["passed"] = audit.passed
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="build-provenance")
    sub = parser.add_subparsers(dest="command", required=True)

    root_cmd = sub.add_parser("merkle-root")
    root_cmd.add_argument("--artifacts", type=Path, required=True)

    ver_cmd = sub.add_parser("verify")
    ver_cmd.add_argument("--chain", type=Path, required=True)
    ver_cmd.add_argument("--key-hex", required=True)
    ver_cmd.add_argument("--ledger", type=Path, default=None)
    ver_cmd.add_argument("--standin-dir", type=Path, default=None)

    insp_cmd = sub.add_parser("inspect-ledger")
    insp_cmd.add_argument("--ledger", type=Path, required=True)
    insp_cmd.add_argument("--key-hex", required=True)

    standin_cmd = sub.add_parser("standin-status")
    standin_cmd.add_argument("--standin-dir", type=Path, required=True)

    args = parser.parse_args(argv)
    if args.command == "merkle-root":
        items = json.loads(args.artifacts.read_text(encoding="utf-8"))
        print(json.dumps({"root": MerkleTree.compute_root(items)}))
        return 0
    if args.command == "verify":
        try:
            stages = load_stage_chain(args.chain)
            pipeline = ProvenancePipeline(
                bytes.fromhex(args.key_hex),
                ledger=_resolve_ledger(args.ledger),
                standin=_resolve_standin(args.standin_dir),
            )
        except (ValueError, json.JSONDecodeError, OSError) as exc:
            print(json.dumps({"passed": False, "error": str(exc), "stages": []}))
            return 1
        audits = pipeline.verify_chain(stages)
        passed = bool(audits) and all(a.passed for a in audits)
        print(json.dumps({"passed": passed, "stages": [_serialize_audit(a) for a in audits]}))
        return 0 if passed else 1
    if args.command == "inspect-ledger":
        try:
            key = bytes.fromhex(args.key_hex)
            if not key:
                raise ValueError("key_hex must not be empty")
            ledger = AttestationLedger(args.ledger)
            entries = ledger.read_all()
            ok = ledger.verify_integrity(key)
        except (ValueError, json.JSONDecodeError, OSError) as exc:
            print(json.dumps({"entries": 0, "integrity_ok": False, "stages": [], "error": str(exc)}))
            return 1
        stages = [e.get("stage_id") if isinstance(e, dict) else None for e in entries]
        print(json.dumps({"entries": len(entries), "integrity_ok": ok, "stages": stages}))
        return 0 if ok else 1
    if args.command == "standin-status":
        print(json.dumps(LocalAttestationStandIn(args.standin_dir).summary()))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
