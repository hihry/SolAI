"""Multi-stage provenance chain verification pipeline."""

from __future__ import annotations

from typing import Any

from .manifest import BuildStage
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
        raise NotImplementedError("Multi-stage provenance chain verification is not implemented yet")
