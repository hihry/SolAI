"""Baseline regression tests for build-provenance."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.manifest import BuildStage
from src.merkle import MerkleTree
from src.verifier import AttestationLedger, is_hermetic_builder


class ProvenanceRegressionTests(unittest.TestCase):
    def test_merkle_root_determinism_and_inclusion_proof(self) -> None:
        a = {"bin/app": "11" * 32, "lib/core.whl": "22" * 32, "conf/policy.json": "33" * 32}
        b = {"conf/policy.json": "33" * 32, "lib/core.whl": "22" * 32, "bin/app": "11" * 32}
        root = MerkleTree.compute_root(a)
        self.assertEqual(root, MerkleTree.compute_root(b))

        proof = MerkleTree.inclusion_proof(a, "lib/core.whl")
        self.assertTrue(MerkleTree.verify_proof("lib/core.whl", "22" * 32, proof, root))
        self.assertFalse(MerkleTree.verify_proof("lib/core.whl", "99" * 32, proof, root))

    def test_stage_hmac_allowlist_and_ledger(self) -> None:
        key = b"unit-test-attestation-key"
        stage_unsigned = BuildStage(
            stage_id="compile",
            builder="python-wheel-builder",
            inputs={"src.tar": "aa" * 32},
            outputs={"pkg.whl": "bb" * 32},
            signature="",
        )
        sig = stage_unsigned.compute_expected_signature(key)
        signed = BuildStage(
            stage_id="compile",
            builder="python-wheel-builder",
            inputs={"src.tar": "aa" * 32},
            outputs={"pkg.whl": "bb" * 32},
            signature=sig,
        )
        self.assertTrue(signed.verify_signature(key))
        self.assertTrue(is_hermetic_builder(signed))

        with tempfile.TemporaryDirectory() as tmp:
            ledger = AttestationLedger(Path(tmp) / "provenance.jsonl")
            ledger.append(signed)
            rows = ledger.read_all()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["stage_id"], "compile")


if __name__ == "__main__":
    unittest.main()
