# Ticket: Adaptive Telemetry Batch Drain

Complete `AdaptiveIngestor.drain_batch` in `/app/src/ingestor.py` and wire the `drain` subcommand in `/app/src/cli.py`.

## Requirements
- Read pending events from `EventBuffer` up to `batch_size` while respecting `TokenBucket` capacity.
- Record delivered event IDs as `flushed` and retain throttled events in `pending` state with incremented retry counts.
- Preserve all existing `EventBuffer` and `TelemetryEvent` regression contracts.
