# Boundary Risk & Defensive Mitigation — `build-provenance` (`CY.AA`)

Reproducible build pipelines enforce hermetic stage boundaries and verify cryptographic Merkle provenance roots between build steps. Executing unverified ambient build hooks introduces artifact tampering risks across downstream releases. Defensive mitigation restricts execution to allowlisted declarative builders and validates continuous provenance digests.
