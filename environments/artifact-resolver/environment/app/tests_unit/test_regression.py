"""Baseline regression tests for artifact-resolver."""
from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from src.cli import main as cli_main
from src.graph import CycleError, DependencyGraph
from src.lockfile import LockedPackage, Lockfile, compute_sha256
from src.resolver import RegistryCatalog, ReleaseMetadata
from src.semver import SemVer, VersionConstraint
from src.standin import StandInRegistryCluster, read_audit_events


class ResolverRegressionTests(unittest.TestCase):
    def test_semver_caret_and_range_matching(self) -> None:
        constraint = VersionConstraint("^1.2.0, <1.5.0")
        candidates = [SemVer.parse("1.1.9"), SemVer.parse("1.2.4"), SemVer.parse("1.4.2"), SemVer.parse("1.5.0")]
        self.assertEqual(str(constraint.select_highest(candidates)), "1.4.2")
        tilde = VersionConstraint("~1.2.1, !=1.2.5, <=1.3.0")
        self.assertEqual(str(tilde.select_highest([SemVer(1, 2, 0), SemVer(1, 2, 4), SemVer(1, 2, 5), SemVer(1, 3, 0)])), "1.2.4")
        narrowed = VersionConstraint(">=1.0.0").intersect(VersionConstraint("<2.0.0"))
        self.assertTrue(narrowed.matches(SemVer(1, 9, 0)))
        self.assertFalse(narrowed.matches(SemVer(2, 0, 0)))
        with self.assertRaises(ValueError):
            VersionConstraint("")

    def test_kahn_topological_sort_and_cycle_detection(self) -> None:
        graph = DependencyGraph()
        graph.add_dependency("service-a", "@corp/auth")
        graph.add_dependency("@corp/auth", "crypto-core")
        self.assertEqual(graph.topological_order(), ["crypto-core", "@corp/auth", "service-a"])
        self.assertIsNone(graph.find_cycle())
        self.assertEqual(graph.dependencies_of("service-a"), ("@corp/auth",))

        graph.add_dependency("crypto-core", "service-a")
        cycle = graph.find_cycle()
        self.assertIsNotNone(cycle)
        self.assertEqual(cycle[0], cycle[-1])
        with self.assertRaises(CycleError):
            graph.topological_order()

    def test_scope_binding_and_digest(self) -> None:
        catalog = RegistryCatalog({"@corp": "internal-artifactory"})
        self.assertTrue(catalog.is_bound_scope("@corp/auth"))
        self.assertFalse(catalog.is_bound_scope("@other/auth"))
        self.assertEqual(catalog.allowed_registry_for("@corp/auth"), "internal-artifactory")
        self.assertEqual(catalog.allowed_registry_for("requests"), "public")
        payload = b"wheel-bytes"
        rel = ReleaseMetadata("@corp/auth", SemVer(1, 0, 0), "internal-artifactory", compute_sha256(payload), payload)
        self.assertTrue(rel.verify_digest())
        bad = ReleaseMetadata("@corp/auth", SemVer(1, 0, 0), "internal-artifactory", "0" * 64, payload)
        self.assertFalse(bad.verify_digest())

    def test_lockfile_roundtrip_and_integrity_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "lockfile.json"
            dep_pkg = LockedPackage("http-core", "1.0.0", "public", compute_sha256(b"http"))
            app_pkg = LockedPackage("@corp/auth", "2.0.0", "internal-artifactory", compute_sha256(b"auth"), ("http-core",))
            Lockfile([dep_pkg, app_pkg]).save(path)
            loaded = Lockfile.load(path)
            self.assertEqual(loaded.verify_integrity({"@corp": "internal-artifactory"}), [])

            bad_order = Lockfile([app_pkg, dep_pkg]).verify_integrity({"@corp": "internal-artifactory"})
            self.assertTrue(any("topological" in v for v in bad_order))
            spoofed = Lockfile([LockedPackage("@corp/auth", "2.0.0", "public", compute_sha256(b"auth"))]).verify_integrity(
                {"@corp": "internal-artifactory"}
            )
            self.assertTrue(any("scope violation" in v for v in spoofed))

    def test_standin_records_queries_and_fetches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index_path = root / "index.json"
            audit_path = root / "audit.jsonl"
            blob = "benign-auth-payload"
            index_path.write_text(json.dumps({
                "scope_bindings": {"@corp": "internal-artifactory"},
                "releases": [{
                    "name": "@corp/auth", "version": "1.2.0", "registry_id": "internal-artifactory",
                    "sha256": compute_sha256(blob.encode("utf-8")), "artifact_content": blob, "requires": {},
                }],
            }), encoding="utf-8")
            with StandInRegistryCluster.seed_from_index(index_path, root / "reg", audit_path, use_http=True) as cluster:
                catalog = RegistryCatalog({"@corp": "internal-artifactory"}, standin_cluster=cluster)
                found = catalog.list_releases("internal-artifactory", "@corp/auth")
                missing = catalog.list_releases("public", "@corp/missing")
            self.assertEqual(len(found), 1)
            self.assertTrue(found[0].verify_digest())
            self.assertEqual(missing, [])
            events = read_audit_events(audit_path)
            self.assertTrue(any(e.registry_id == "internal-artifactory" and e.package_name == "@corp/auth" and e.found for e in events))
            self.assertTrue(any(e.registry_id == "public" and e.package_name == "@corp/missing" and not e.found for e in events))

    def test_cli_check_scope_and_verify_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index_path = root / "index.json"
            lock_path = root / "lock.json"
            index_path.write_text(json.dumps({"scope_bindings": {"@corp": "internal-artifactory"}, "releases": []}), encoding="utf-8")
            Lockfile([LockedPackage("@corp/auth", "1.0.0", "internal-artifactory", compute_sha256(b"a"))]).save(lock_path)

            out = io.StringIO()
            with redirect_stdout(out):
                rc = cli_main(["--index", str(index_path), "check-scope", "--package", "@corp/auth"])
            self.assertEqual(rc, 0)
            self.assertEqual(json.loads(out.getvalue())["registry_id"], "internal-artifactory")

            out2 = io.StringIO()
            with redirect_stdout(out2):
                rc2 = cli_main(["--index", str(index_path), "verify-lock", "--lockfile", str(lock_path)])
            self.assertEqual(rc2, 0)
            self.assertTrue(json.loads(out2.getvalue())["valid"])


if __name__ == "__main__":
    unittest.main()
