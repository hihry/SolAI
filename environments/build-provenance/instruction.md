# Ticket: Multi-Stage Provenance Chain Verifier

Implement `ProvenancePipeline.verify_chain` in `/app/src/pipeline.py` and wire the `verify` subcommand in `/app/src/cli.py`.

## Requirements
- Validate stage input/output Merkle roots across sequential `BuildStage` attestations.
- Ensure every executed step uses only declarative `ALLOWED_BUILDERS` without external hook injection.
- Preserve existing `MerkleTree` and canonical JSON attestation behavior.
