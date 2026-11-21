"""Deterministic SHA-256 Merkle tree and inclusion proofs over artifact digests."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any


def canonical_json_bytes(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def leaf_digest(name: str, sha256_hex: str) -> str:
    raw = f"leaf::{name}::{sha256_hex}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def pair_digest(left: str, right: str) -> str:
    raw = f"node::{left}::{right}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class ProofStep:
    sibling_hash: str
    sibling_on_left: bool


class MerkleTree:
    @staticmethod
    def _build_levels(artifacts: dict[str, str]) -> tuple[list[str], list[list[str]]]:
        names = sorted(artifacts)
        leaves = [leaf_digest(name, artifacts[name]) for name in names]
        levels: list[list[str]] = [leaves]
        current = leaves
        while len(current) > 1:
            nxt: list[str] = []
            for idx in range(0, len(current), 2):
                left = current[idx]
                right = current[idx + 1] if idx + 1 < len(current) else left
                nxt.append(pair_digest(left, right))
            levels.append(nxt)
            current = nxt
        return names, levels

    @staticmethod
    def compute_root(artifacts: dict[str, str]) -> str:
        if not artifacts:
            return hashlib.sha256(b"empty-tree").hexdigest()
        _, levels = MerkleTree._build_levels(artifacts)
        return levels[-1][0]

    @staticmethod
    def inclusion_proof(artifacts: dict[str, str], target_name: str) -> list[ProofStep]:
        if target_name not in artifacts:
            raise KeyError(f"artifact not in tree: {target_name}")
        names, levels = MerkleTree._build_levels(artifacts)
        pos = names.index(target_name)
        proof: list[ProofStep] = []
        for level in levels[:-1]:
            if pos % 2 == 0:
                sib_idx = pos + 1 if pos + 1 < len(level) else pos
                proof.append(ProofStep(sibling_hash=level[sib_idx], sibling_on_left=False))
            else:
                proof.append(ProofStep(sibling_hash=level[pos - 1], sibling_on_left=True))
            pos //= 2
        return proof

    @staticmethod
    def verify_proof(name: str, sha256_hex: str, proof: list[ProofStep], expected_root: str) -> bool:
        acc = leaf_digest(name, sha256_hex)
        for step in proof:
            if step.sibling_on_left:
                acc = pair_digest(step.sibling_hash, acc)
            else:
                acc = pair_digest(acc, step.sibling_hash)
        return acc == expected_root
