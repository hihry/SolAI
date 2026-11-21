"""Baseline regression tests for build-provenance."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from src import cli
from src.manifest import BuildStage
from src.merkle import MerkleTree
from src.standin import LocalAttestationStandIn
from src.verifier import AttestationLedger, StageAudit, check_stage_policy, is_hermetic_builder


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
            self.assertTrue(ledger.verify_integrity(key))

    def test_from_dict_captures_forbidden_hooks_and_policy_rejects(self) -> None:
        hooked = BuildStage.from_dict(
            {
                "stage_id": "compile",
                "builder": "python-wheel-builder",
                "inputs": {"src.tar": "aa" * 32},
                "outputs": {"pkg.whl": "bb" * 32},
                "signature": "00" * 32,
                "pre_build": "echo ambient",
            }
        )
        self.assertTrue(hooked.hooks)
        self.assertFalse(is_hermetic_builder(hooked))
        ok, reasons = check_stage_policy(hooked)
        self.assertFalse(ok)
        self.assertTrue(any(r.startswith("forbidden_hooks:") for r in reasons))

    def test_standin_records_events_and_receipts(self) -> None:
        key = b"standin-unit-key"
        base = BuildStage(
            stage_id="pack",
            builder="container-layer-packer",
            inputs={"pkg.whl": "bb" * 32},
            outputs={"layer.tar": "cc" * 32},
            signature="",
        )
        signed = BuildStage(
            stage_id="pack",
            builder="container-layer-packer",
            inputs={"pkg.whl": "bb" * 32},
            outputs={"layer.tar": "cc" * 32},
            signature=base.compute_expected_signature(key),
        )
        with tempfile.TemporaryDirectory() as tmp:
            standin = LocalAttestationStandIn(Path(tmp) / "standin")
            audit = StageAudit("pack", True, True, True)
            standin.record_stage_event(signed, audit, expected_prev_root=None)
            standin.record_ledger_commit(signed)
            self.assertEqual(len(standin.read_events()), 1)
            self.assertEqual(len(standin.read_receipts()), 1)
            self.assertEqual(standin.read_registry()["total_verified"], 1)

    def test_from_dict_rejects_non_string_ids_and_preserves_blank_hooks(self) -> None:
        base_entry = {
            "stage_id": "compile",
            "builder": "python-wheel-builder",
            "inputs": {"src.tar": "aa" * 32},
            "outputs": {"pkg.whl": "bb" * 32},
            "signature": "00" * 32,
        }
        with self.assertRaises(ValueError):
            BuildStage.from_dict({**base_entry, "stage_id": None})
        with self.assertRaises(ValueError):
            BuildStage.from_dict({**base_entry, "builder": None})

        blank_hooked = BuildStage.from_dict({**base_entry, "hooks": ["   "]})
        self.assertTrue(blank_hooked.hooks)
        self.assertFalse(is_hermetic_builder(blank_hooked))
        ok, reasons = check_stage_policy(blank_hooked)
        self.assertFalse(ok)
        self.assertTrue(any(r.startswith("forbidden_hooks:") for r in reasons))

    def test_cli_verify_missing_chain_returns_structured_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing.json"
            stdout_buf = io.StringIO()
            stderr_buf = io.StringIO()
            with contextlib.redirect_stdout(stdout_buf), contextlib.redirect_stderr(stderr_buf):
                rc = cli.main(["verify", "--chain", str(missing), "--key-hex", "0102"])
            self.assertEqual(rc, 1)
            self.assertEqual(stderr_buf.getvalue(), "")
            payload = json.loads(stdout_buf.getvalue().strip())
            self.assertFalse(payload["passed"])
            self.assertEqual(payload["stages"], [])
            self.assertTrue(payload["error"])


if __name__ == "__main__":
    unittest.main()
