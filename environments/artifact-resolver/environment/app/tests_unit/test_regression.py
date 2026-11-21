"""Baseline regression tests for artifact-resolver."""

from __future__ import annotations

import unittest

from src.graph import CycleError, DependencyGraph
from src.lockfile import compute_sha256
from src.resolver import RegistryCatalog, ReleaseMetadata
from src.semver import SemVer, VersionConstraint


class ResolverRegressionTests(unittest.TestCase):
    def test_semver_caret_and_range_matching(self) -> None:
        constraint = VersionConstraint("^1.2.0, <1.5.0")
        candidates = [SemVer.parse("1.1.9"), SemVer.parse("1.2.4"), SemVer.parse("1.4.2"), SemVer.parse("1.5.0")]
        best = constraint.select_highest(candidates)
        self.assertEqual(str(best), "1.4.2")

    def test_kahn_topological_sort_and_cycle_detection(self) -> None:
        graph = DependencyGraph()
        graph.add_dependency("service-a", "@corp/auth")
        graph.add_dependency("@corp/auth", "crypto-core")
        self.assertEqual(graph.topological_order(), ["crypto-core", "@corp/auth", "service-a"])

        graph.add_dependency("crypto-core", "service-a")
        with self.assertRaises(CycleError):
            graph.topological_order()

    def test_scope_binding_and_digest(self) -> None:
        catalog = RegistryCatalog({"@corp": "internal-artifactory"})
        self.assertEqual(catalog.allowed_registry_for("@corp/auth"), "internal-artifactory")
        self.assertEqual(catalog.allowed_registry_for("requests"), "public")
        payload = b"wheel-bytes"
        rel = ReleaseMetadata("@corp/auth", SemVer(1, 0, 0), "internal-artifactory", compute_sha256(payload), payload)
        self.assertTrue(rel.verify_digest())


if __name__ == "__main__":
    unittest.main()
