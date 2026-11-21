# Ticket: Scoped Transitive Lockfile Resolution

Implement `DependencyResolver.resolve_lockfile` in `/app/src/resolver.py` and enable the `lock` subcommand in `/app/src/cli.py`.

## Requirements
- Resolve root and transitive package requirements in deterministic topological order.
- Enforce scope-to-registry mapping and verify SHA-256 artifact digests before emitting `Lockfile` entries.
- Reject dependency cycles cleanly while preserving existing `SemVer` and `Lockfile` behavior.
