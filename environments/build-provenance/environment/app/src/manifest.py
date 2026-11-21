"""Declarative build stage specifications and HMAC attestation tags."""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .merkle import MerkleTree, canonical_json_bytes

ALLOWED_BUILDERS = frozenset({
    "python-wheel-builder",
    "static-asset-bundler",
    "container-layer-packer",
})

FORBIDDEN_HOOK_KEYS = frozenset({
    "hook", "hooks", "pre_build", "post_build", "pre_step", "post_step",
    "shell", "command", "script", "exec", "plugin", "plugin_path", "lifecycle_hook",
})


@dataclass(frozen=True)
class BuilderProfile:
    """Declarative metadata for a hermetic builder implementation."""

    name: str
    allowed_outputs: tuple[str, ...]
    hermetic: bool = True
    description: str = ""


BUILDER_PROFILES: dict[str, BuilderProfile] = {
    "python-wheel-builder": BuilderProfile(
        "python-wheel-builder", (".whl", ".tar.gz", ".json"), True, "PEP 517 Python wheel packager."
    ),
    "static-asset-bundler": BuilderProfile(
        "static-asset-bundler", (".js", ".css", ".wasm", ".tar", ".json"), True, "Static web asset bundler."
    ),
    "container-layer-packer": BuilderProfile(
        "container-layer-packer", (".tar", ".tar.gz", ".oci", ".json"), True, "Canonical OCI layer archiver."
    ),
}


def _validate_digest_map(mapping: dict[str, str], label: str) -> None:
    if not isinstance(mapping, dict):
        raise ValueError(f"{label} must be a mapping of artifact paths to sha256 hex digests")
    for artifact_name, digest in mapping.items():
        if not isinstance(artifact_name, str) or not artifact_name or ".." in artifact_name or artifact_name.startswith("/"):
            raise ValueError(f"invalid relative artifact path in {label}: {artifact_name}")
        if not isinstance(digest, str) or len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise ValueError(f"invalid lowercase sha256 hex in {label} for {artifact_name}")


@dataclass(frozen=True)
class BuildStage:
    stage_id: str
    builder: str
    inputs: dict[str, str]
    outputs: dict[str, str]
    signature: str
    hooks: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, entry: dict[str, Any]) -> BuildStage:
        if not isinstance(entry, dict):
            raise ValueError("build stage entry must be a JSON object")
        required = ("stage_id", "builder", "inputs", "outputs", "signature")
        for field_name in required:
            if field_name not in entry:
                raise ValueError(f"missing required stage field: {field_name}")
        if not isinstance(entry["stage_id"], str):
            raise ValueError("stage_id must be a string")
        if not isinstance(entry["builder"], str):
            raise ValueError("builder must be a string")

        collected_hooks: list[str] = []
        raw_hooks = entry.get("hooks")
        if isinstance(raw_hooks, (list, tuple)):
            for item in raw_hooks:
                text = str(item).strip()
                collected_hooks.append(f"hooks:{text if text else 'blank'}")
        elif raw_hooks not in (None, "", ()):
            text = str(raw_hooks).strip()
            collected_hooks.append(f"hooks:{text if text else 'blank'}")

        allowed_top_keys = set(required) | {"hooks"}
        for key, value in entry.items():
            if key in FORBIDDEN_HOOK_KEYS - {"hooks"} or key not in allowed_top_keys:
                collected_hooks.append(f"{key}:{value}")

        return cls(
            stage_id=entry["stage_id"],
            builder=entry["builder"],
            inputs=entry["inputs"],
            outputs=entry["outputs"],
            signature=str(entry["signature"]),
            hooks=tuple(collected_hooks),
        )

    def validate_structure(self) -> None:
        if not isinstance(self.stage_id, str) or not self.stage_id or not self.stage_id.replace("-", "").isalnum():
            raise ValueError(f"invalid stage_id: {self.stage_id}")
        if not isinstance(self.builder, str) or not self.builder.strip():
            raise ValueError("builder must be non-empty")
        if not isinstance(self.signature, str):
            raise ValueError("signature must be a string")
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
        return hmac.compare_digest(self.compute_expected_signature(key), self.signature)


def load_stage_chain(chain_path: Path) -> list[BuildStage]:
    raw_stages = json.loads(Path(chain_path).read_text(encoding="utf-8"))
    if not isinstance(raw_stages, list):
        raise ValueError("provenance chain manifest must be a JSON list of stages")
    return [BuildStage.from_dict(entry) for entry in raw_stages]
