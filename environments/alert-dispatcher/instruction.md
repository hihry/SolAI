# Ticket: Deduplicated Incident Digest Dispatcher

Implement `AlertRouter.dispatch_digest` in `/app/src/router.py` and connect the `digest` subcommand in `/app/src/cli.py`.

## Requirements
- Deduplicate incoming `IncidentSignal` items by fingerprint while tracking occurrence counts and peak severity.
- Render plain-text operational summaries referencing only verified read-only dashboard origins.
- Maintain all existing `Deduplicator` and `SummaryFormatter` validation invariants.
