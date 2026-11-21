"""Stage policy checks and append-only provenance ledger."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .manifest import ALLOWED_BUILDERS, BuildStage


@dataclass(frozen=True)
class StageAudit:
    stage_id: str
    builder_allowed: bool
    signature_valid: bool
    chain_linked: bool

    @property
    def passed(self) -> bool:
        return self.builder_allowed and self.signature_valid and self.chain_linked


def is_hermetic_builder(stage: BuildStage) -> bool:
    return stage.builder in ALLOWED_BUILDERS


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

    def read_all(self) -> list[dict[str, str]]:
        if not self.ledger_path.exists():
            return []
        entries: list[dict[str, str]] = []
        for line in self.ledger_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                entries.append(json.loads(line))
        return entries
