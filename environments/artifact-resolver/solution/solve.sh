#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/app}"

python3 -B - "$APP_DIR" <<'PYEOF'
from pathlib import Path
import sys

app_dir = Path(sys.argv[1])
resolver_path = app_dir / "src" / "resolver.py"
cli_path = app_dir / "src" / "cli.py"

resolver_src = resolver_path.read_text(encoding="utf-8")

old_imports = "from .lockfile import Lockfile, compute_sha256, verify_sha256\nfrom .semver import SemVer"
new_imports = (
    "from collections import deque\n"
    "from .graph import DependencyGraph\n"
    "from .lockfile import LockedPackage, Lockfile, compute_sha256, verify_sha256\n"
    "from .semver import SemVer, VersionConstraint"
)
if new_imports not in resolver_src:
    assert old_imports in resolver_src, "Expected import block not found in src/resolver.py"
    resolver_src = resolver_src.replace(old_imports, new_imports, 1)

stub_method = '''    def resolve_lockfile(self, root_requirements: dict[str, str]) -> Lockfile:
        """Resolve transitive requirements using pinned scope bindings and digest verification."""
        raise NotImplementedError("Transitive scoped lockfile resolution is not implemented yet")'''

impl_method = '''    def _sync_reachable(
        self,
        root_requirements: dict[str, str],
        resolved: dict[str, ReleaseMetadata],
    ) -> tuple[dict[str, ReleaseMetadata], dict[str, VersionConstraint]]:
        clauses: dict[str, list[str]] = {}
        for pkg, expr in sorted(root_requirements.items()):
            clauses.setdefault(pkg, []).append(expr)
        reachable: dict[str, ReleaseMetadata] = {}
        walk = deque(sorted(root_requirements.keys()))
        visited: set[str] = set()
        while walk:
            cur = walk.popleft()
            if cur in visited:
                continue
            visited.add(cur)
            rel = resolved.get(cur)
            if rel is None:
                continue
            reachable[cur] = rel
            for dep_name, dep_expr in sorted(rel.requires.items()):
                dep_list = clauses.setdefault(dep_name, [])
                if dep_expr not in dep_list:
                    dep_list.append(dep_expr)
                if dep_name not in visited:
                    walk.append(dep_name)
        constraints = {pkg: VersionConstraint(", ".join(exprs)) for pkg, exprs in clauses.items()}
        return reachable, constraints

    def resolve_lockfile(self, root_requirements: dict[str, str]) -> Lockfile:
        """Resolve transitive requirements using pinned scope bindings and digest verification."""
        if not root_requirements:
            return Lockfile([])

        resolved: dict[str, ReleaseMetadata] = {}
        selected_expr: dict[str, str] = {}
        deferred: set[str] = set()
        steps = 0

        while True:
            resolved, constraints = self._sync_reachable(root_requirements, resolved)
            selected_expr = {k: v for k, v in selected_expr.items() if k in resolved}
            invalidated = [p for p in constraints if p in resolved and not constraints[p].matches(resolved[p].version)]
            relaxed = [
                p for p in constraints
                if p in resolved and constraints[p].matches(resolved[p].version) and selected_expr.get(p) != constraints[p].expr
            ]
            unresolved = [p for p in constraints if p not in resolved]

            candidates_order = [p for p in relaxed + invalidated + unresolved if p not in deferred]
            if not candidates_order:
                if not deferred:
                    break
                pkg = sorted(deferred)[0]
                deferred.clear()
                allow_defer = False
            else:
                pkg = candidates_order[0]
                allow_defer = len(candidates_order) > 1

            steps += 1
            if steps > max(100, len(constraints) * 25):
                raise ResolutionError("dependency constraint convergence limit exceeded")
            if pkg.startswith("@"):
                if "/" not in pkg or not self.catalog.is_bound_scope(pkg):
                    raise ScopeViolationError(f"unbound scoped package rejected: {pkg}")
            target_reg = self.catalog.allowed_registry_for(pkg, default_registry=self.default_registry)
            if pkg.startswith("@") and target_reg == self.default_registry:
                scope = pkg.split("/", 1)[0]
                if scope not in self.catalog.scope_bindings:
                    raise ScopeViolationError(f"scoped package {pkg} cannot fall back to {self.default_registry}")

            releases = [rel for rel in self.catalog.list_releases(target_reg, pkg) if rel.registry_id == target_reg]
            constraint = constraints[pkg]
            compatible = [rel for rel in releases if constraint.matches(rel.version)]
            if not compatible:
                if allow_defer:
                    deferred.add(pkg)
                    continue
                raise MissingPackageError(
                    f"no compatible release for {pkg} ({constraint.expr}) in registry {target_reg}"
                )
            best = max(compatible, key=lambda rel: rel.version)
            if not best.verify_digest():
                raise DigestMismatchError(f"SHA-256 digest mismatch for {pkg}@{best.version}")

            prev = resolved.get(pkg)
            selected_expr[pkg] = constraint.expr
            if prev is None or prev.version != best.version:
                resolved[pkg] = best
                deferred.clear()

        graph = DependencyGraph()
        walk = deque(sorted(root_requirements.keys()))
        visited: set[str] = set()
        while walk:
            cur = walk.popleft()
            if cur in visited:
                continue
            visited.add(cur)
            graph.add_node(cur)
            for dep_name in sorted(resolved[cur].requires.keys()):
                graph.add_dependency(cur, dep_name)
                if dep_name not in visited:
                    walk.append(dep_name)

        ordered = graph.topological_order()
        packages = [
            LockedPackage(
                name=name,
                version=str(resolved[name].version),
                registry_id=resolved[name].registry_id,
                sha256=resolved[name].expected_sha256,
                dependencies=tuple(sorted(resolved[name].requires.keys())),
            )
            for name in ordered
        ]
        return Lockfile(packages)'''

if stub_method in resolver_src:
    resolver_src = resolver_src.replace(stub_method, impl_method, 1)
resolver_path.write_text(resolver_src, encoding="utf-8")

cli_src = cli_path.read_text(encoding="utf-8")
old_cli_import = "from .resolver import RegistryCatalog, ReleaseMetadata, ResolutionError"
new_cli_import = "from .resolver import DependencyResolver, RegistryCatalog, ReleaseMetadata, ResolutionError"
if new_cli_import not in cli_src:
    assert old_cli_import in cli_src, "Expected import not found in src/cli.py"
    cli_src = cli_src.replace(old_cli_import, new_cli_import, 1)

old_lock_branch = '''        if args.command == "lock":
            raise NotImplementedError("lock subcommand is not enabled yet")'''
new_lock_branch = '''        if args.command == "lock":
            manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
            lockfile = DependencyResolver(catalog).resolve_lockfile(manifest.get("dependencies", {}))
            lockfile.save(args.output)
            print(json.dumps({"locked_packages": len(lockfile.packages), "output": str(args.output)}))
            return 0'''
if old_lock_branch in cli_src:
    cli_src = cli_src.replace(old_lock_branch, new_lock_branch, 1)
cli_path.write_text(cli_src, encoding="utf-8")
PYEOF
