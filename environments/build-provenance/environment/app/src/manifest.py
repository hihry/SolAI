"""Declarative build stage specifications and HMAC attestation tags."""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import Any

from .merkle import MerkleTree, canonical_json_bytes


ALLOWED_BUILDERS = frozenset(
    {
        "python-wheel-builder",
        "static-asset-bundler",
        "container-layer-packer",
    }
)


def _validate_digest_map(mapping: dict[str, str], label: str) -> None:
    for artifact_name, digest in mapping.items():
        if not artifact_name or ".." in artifact_name or artifact_name.startswith("/"):
            raise ValueError(f"invalid relative artifact path in {label}: {artifact_name}")
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise ValueError(f"invalid lowercase sha256 hex in {label} for {artifact_name}")


@dataclass(frozen=True)
class BuildStage:
    stage_id: str
    builder: str
    inputs: dict[str, str]
    outputs: dict[str, str]
    signature: str

    def validate_structure(self) -> None:
        if not self.stage_id or not self.stage_id.replace("-", "").isalnum():
            raise ValueError(f"invalid stage_id: {self.stage_id}")
        if not self.builder.strip():
            raise ValueError("builder must be non-empty")
        _validate_digest_map(self.inputs, "inputs")
        _validate_digest_map(self.outputs, "outputs")

    def input_root(self) -> str:
        self.validate_structure()
        return MerkleTree.compute_root(self.inputs)

    def output_root(self) -> str:
        self.validate_structure()
        return MerkleTree.compute_root(self.outputs)

    def unsigned_payload(self) -> dict[str, Any]:
        return {
            "stage_id": self.stage_id,
            "builder": self.builder,
            "input_root": self.input_root(),
            "output_root": self.output_root(),
        }

    def compute_expected_signature(self, key: bytes) -> str:
        return hmac.new(key, canonical_json_bytes(self.unsigned_payload()), hashlib.sha256).hexdigest()

    def verify_signature(self, key: bytes) -> bool:
        expected = self.compute_expected_signature(key)
        return hmac.compare_digest(expected, self.signature)
