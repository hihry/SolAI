"""Stage policy checks and append-only provenance ledger."""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .manifest import ALLOWED_BUILDERS, BUILDER_PROFILES, BuildStage
from .merkle import canonical_json_bytes


@dataclass(frozen=True)
class StageAudit:
    stage_id: str
    builder_allowed: bool
    signature_valid: bool
    chain_linked: bool
    reasons: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        return self.builder_allowed and self.signature_valid and self.chain_linked


def is_hermetic_builder(stage: BuildStage) -> bool:
    profile = BUILDER_PROFILES.get(stage.builder)
    return stage.builder in ALLOWED_BUILDERS and bool(profile and profile.hermetic) and not stage.hooks


def check_stage_policy(stage: BuildStage) -> tuple[bool, list[str]]:
    """Evaluate declarative builder and structural hermeticity rules without executing hooks."""
    reasons: list[str] = []
    try:
        stage.validate_structure()
    except (ValueError, TypeError) as exc:
        reasons.append(f"invalid_structure:{exc}")
    if stage.builder not in ALLOWED_BUILDERS:
        reasons.append(f"untrusted_builder:{stage.builder}")
    if stage.hooks:
        reasons.append(f"forbidden_hooks:{','.join(stage.hooks)}")
    return (len(reasons) == 0, reasons)


class AttestationLedger:
    """Append-only local JSONL store for verified stage payloads."""

    def __init__(self, ledger_path: Path) -> None:
        self.ledger_path = Path(ledger_path)
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, stage: BuildStage) -> None:
        record = stage.unsigned_payload()
        record["signature"] = stage.signature
        with self.ledger_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")

    def read_all(self) -> list[dict[str, Any]]:
        if not self.ledger_path.exists():
            return []
        entries: list[dict[str, Any]] = []
        for line in self.ledger_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                entries.append(json.loads(line))
        return entries

    def verify_integrity(self, key: bytes) -> bool:
        """Re-verify builder allowlist membership and HMAC tags across stored entries."""
        required_keys = ("stage_id", "builder", "input_root", "output_root", "signature")
        try:
            entries = self.read_all()
        except json.JSONDecodeError:
            return False
        for row in entries:
            if not isinstance(row, dict) or any(k not in row for k in required_keys):
                return False
            if row["builder"] not in ALLOWED_BUILDERS:
                return False
            unsigned = {
                "stage_id": row["stage_id"],
                "builder": row["builder"],
                "input_root": row["input_root"],
                "output_root": row["output_root"],
            }
            expected = hmac.new(key, canonical_json_bytes(unsigned), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected, str(row["signature"])):
                return False
        return True
