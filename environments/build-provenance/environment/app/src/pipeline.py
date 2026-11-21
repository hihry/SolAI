"""Multi-stage provenance chain verification pipeline."""

from __future__ import annotations

from .manifest import BuildStage
from .verifier import StageAudit


class ProvenancePipeline:
    def __init__(self, attestation_key: bytes) -> None:
        if not attestation_key:
            raise ValueError("attestation_key must not be empty")
        self.attestation_key = attestation_key

    def verify_chain(self, stages: list[BuildStage]) -> list[StageAudit]:
        """Verify signatures, hermetic builders, and input/output Merkle root continuity across stages."""
        raise NotImplementedError("Multi-stage provenance chain verification is not implemented yet")
