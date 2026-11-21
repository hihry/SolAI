"""Command-line interface for telemetry-ingestor."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .buffer import EventBuffer
from .ingestor import AdaptiveIngestor
from .schema import TelemetryEvent
from .sink import LocalJournalSink, TokenBucket


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="telemetry-ingestor")
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--journal", type=Path, required=True)
    sub = parser.add_subparsers(dest="command", required=True)

    enq = sub.add_parser("enqueue")
    enq.add_argument("--input", type=Path, required=True)

    sub.add_parser("status")

    drn = sub.add_parser("drain")
    drn.add_argument("--batch-size", type=int, default=10)
    drn.add_argument("--tokens", type=int, default=10)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    buf = EventBuffer(args.db)
    sink = LocalJournalSink(args.journal)
    bucket = TokenBucket(capacity=50, tokens=float(getattr(args, "tokens", 10)), refill_per_tick=5.0)
    ingestor = AdaptiveIngestor(buf, sink, bucket)

    if args.command == "enqueue":
        raw = json.loads(args.input.read_text(encoding="utf-8"))
        events = [TelemetryEvent(**item) for item in raw]
        count = ingestor.ingest(events)
        print(json.dumps({"enqueued": count}))
        return 0
    if args.command == "status":
        print(json.dumps({"counts": buf.counts_by_status(), "rollup": ingestor.pending_rollup()}))
        return 0
    if args.command == "drain":
        summary = ingestor.drain_batch(batch_size=args.batch_size)
        print(json.dumps(summary.to_dict()))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
