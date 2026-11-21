#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/app}"

cat > "$APP_DIR/src/pipeline.py" <<'PY'
"""Multi-stage provenance chain verification pipeline."""

from __future__ import annotations

from typing import Any

from .manifest import ALLOWED_BUILDERS, BuildStage
from .standin import LocalAttestationStandIn
from .verifier import AttestationLedger, StageAudit


class ProvenancePipeline:
    def __init__(
        self,
        attestation_key: bytes,
        ledger: AttestationLedger | None = None,
        standin: LocalAttestationStandIn | None = None,
        expected_initial_root: str | None = None,
    ) -> None:
        if not attestation_key:
            raise ValueError("attestation_key must not be empty")
        self.attestation_key = attestation_key
        self.ledger = ledger
        self.standin = standin if standin is not None else LocalAttestationStandIn.from_env()
        self.expected_initial_root = expected_initial_root

    @staticmethod
    def summarize_audits(audits: list[StageAudit]) -> dict[str, Any]:
        passed = bool(audits) and all(audit.passed for audit in audits)
        return {
            "stage_count": len(audits),
            "passed": passed,
            "failed_stages": [audit.stage_id for audit in audits if not audit.passed],
        }

    def verify_chain(self, stages: list[BuildStage]) -> list[StageAudit]:
        """Verify signatures, hermetic builders, and input/output Merkle root continuity across stages."""
        if not stages:
            return []

        audits: list[StageAudit] = []
        seen_stage_ids: set[str] = set()
        prev_output_root: str | None = self.expected_initial_root

        for idx, stage in enumerate(stages):
            reasons: list[str] = []
            try:
                in_root = stage.input_root()
                out_root = stage.output_root()
                structure_ok = True
            except (ValueError, TypeError) as exc:
                in_root, out_root = None, None
                structure_ok = False
                reasons.append(f"invalid_structure:{exc}")

            in_allowlist = stage.builder in ALLOWED_BUILDERS
            no_hooks = not stage.hooks
            builder_allowed = in_allowlist and no_hooks
            if not in_allowlist:
                reasons.append(f"untrusted_builder:{stage.builder}")
            if not no_hooks:
                reasons.append(f"forbidden_hooks:{','.join(stage.hooks)}")

            signature_valid = stage.verify_signature(self.attestation_key) if structure_ok else False
            if not signature_valid:
                reasons.append("invalid_signature")

            if stage.stage_id in seen_stage_ids:
                chain_linked = False
                reasons.append(f"duplicate_stage_id:{stage.stage_id}")
            elif not structure_ok:
                chain_linked = False
            elif idx == 0:
                chain_linked = True if self.expected_initial_root is None else (in_root == self.expected_initial_root)
                if not chain_linked:
                    reasons.append("initial_root_mismatch")
            else:
                chain_linked = prev_output_root is not None and in_root == prev_output_root
                if not chain_linked:
                    reasons.append("broken_merkle_linkage")

            audit = StageAudit(
                stage_id=stage.stage_id,
                builder_allowed=builder_allowed,
                signature_valid=signature_valid,
                chain_linked=chain_linked,
                reasons=tuple(reasons),
            )
            audits.append(audit)
            if self.standin is not None:
                self.standin.record_stage_event(stage, audit, expected_prev_root=prev_output_root)

            seen_stage_ids.add(stage.stage_id)
            prev_output_root = out_root if structure_ok else None

        if audits and all(audit.passed for audit in audits):
            if self.ledger is not None:
                for stage in stages:
                    self.ledger.append(stage)
            if self.standin is not None:
                for stage in stages:
                    self.standin.record_ledger_commit(stage)

        return audits
PY

cat > "$APP_DIR/src/cli.py" <<'PY'
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
PY

(cd "$APP_DIR" && python3 -B -m unittest discover -s tests_unit -p "test_*.py" >/dev/null)
