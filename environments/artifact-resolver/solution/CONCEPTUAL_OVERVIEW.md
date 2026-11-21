# Conceptual Defensive Architecture — `artifact-resolver`

Package resolution engines must bind internal organization scopes to explicit registries and cryptographic SHA-256 digests. Unscoped fallback queries across external indices expose transitive dependency graphs to namespace shadowing risks. Defensive mitigation enforces strict scope pinning and deterministic lockfile digest verification.
