"""Local declarative builder registry and attestation service stand-in."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from .manifest import BUILDER_PROFILES, BuildStage
from .merkle import canonical_json_bytes
from .verifier import StageAudit


class LocalAttestationStandIn:
    """File-backed local stand-in recording stage evaluations, builder counts, and receipts."""

    def __init__(self, standin_dir: Path) -> None:
        self.standin_dir = Path(standin_dir)
        self.standin_dir.mkdir(parents=True, exist_ok=True)
        self.registry_path = self.standin_dir / "builder_registry.json"
        self.events_path = self.standin_dir / "stage_events.jsonl"
        self.receipts_path = self.standin_dir / "ledger_receipts.jsonl"
        self._ensure_registry()

    @classmethod
    def from_env(cls, default_dir: Path | None = None) -> LocalAttestationStandIn | None:
        env_path = os.environ.get("PROVENANCE_STANDIN_DIR", "").strip()
        if env_path:
            return cls(Path(env_path))
        return cls(default_dir) if default_dir is not None else None

    def _ensure_registry(self) -> None:
        if self.registry_path.exists():
            return
        initial = {
            "builders": {
                name: {
                    "hermetic": profile.hermetic,
                    "allowed_outputs": list(profile.allowed_outputs),
                    "verified_count": 0,
                    "rejected_count": 0,
                }
                for name, profile in sorted(BUILDER_PROFILES.items())
            },
            "untrusted_builders": [],
            "total_verified": 0,
            "total_rejected": 0,
        }
        self.registry_path.write_text(json.dumps(initial, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def record_stage_event(
        self, stage: BuildStage, audit: StageAudit, expected_prev_root: str | None = None
    ) -> dict[str, Any]:
        try:
            in_root, out_root = stage.input_root(), stage.output_root()
        except (ValueError, TypeError):
            in_root, out_root = "invalid-structure", "invalid-structure"

        event: dict[str, Any] = {
            "seq": len(self.read_events()) + 1,
            "stage_id": stage.stage_id,
            "builder": stage.builder,
            "builder_allowed": audit.builder_allowed,
            "hermetic": not stage.hooks,
            "hooks": list(stage.hooks),
            "signature_valid": audit.signature_valid,
            "chain_linked": audit.chain_linked,
            "input_root": in_root,
            "output_root": out_root,
            "expected_prev_root": expected_prev_root,
            "status": "verified" if audit.passed else "rejected",
            "reasons": list(audit.reasons),
        }
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True) + "\n")

        registry = self.read_registry()
        builders = registry.setdefault("builders", {})
        if stage.builder in builders:
            counter = "verified_count" if audit.passed else "rejected_count"
            builders[stage.builder][counter] = builders[stage.builder].get(counter, 0) + 1
        else:
            untrusted = set(registry.get("untrusted_builders", []))
            untrusted.add(stage.builder)
            registry["untrusted_builders"] = sorted(untrusted)
        total_key = "total_verified" if audit.passed else "total_rejected"
        registry[total_key] = registry.get(total_key, 0) + 1
        self.registry_path.write_text(json.dumps(registry, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return event

    def record_ledger_commit(self, stage: BuildStage) -> dict[str, Any]:
        payload = stage.unsigned_payload()
        receipt_body = {
            "stage_id": payload["stage_id"],
            "builder": payload["builder"],
            "input_root": payload["input_root"],
            "output_root": payload["output_root"],
            "signature": stage.signature,
        }
        digest = hashlib.sha256(canonical_json_bytes(receipt_body)).hexdigest()
        receipt = {**receipt_body, "receipt_digest": digest}
        with self.receipts_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(receipt, sort_keys=True) + "\n")
        return receipt

    def read_events(self) -> list[dict[str, Any]]:
        if not self.events_path.exists():
            return []
        return [json.loads(line) for line in self.events_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def read_receipts(self) -> list[dict[str, Any]]:
        if not self.receipts_path.exists():
            return []
        return [json.loads(line) for line in self.receipts_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def read_registry(self) -> dict[str, Any]:
        self._ensure_registry()
        return json.loads(self.registry_path.read_text(encoding="utf-8"))

    def summary(self) -> dict[str, Any]:
        return {
            "standin_dir": str(self.standin_dir),
            "event_count": len(self.read_events()),
            "receipt_count": len(self.read_receipts()),
            "registry": self.read_registry(),
        }
