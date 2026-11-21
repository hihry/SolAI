"""CLI entrypoint for alert-dispatcher."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .formatter import SummaryFormatter
from .incidents import IncidentSignal
from .router import AlertRouter


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="alert-dispatcher")
    parser.add_argument("--outbox", type=Path, required=True)
    parser.add_argument("--origin", default="https://status.internal.example")
    sub = parser.add_subparsers(dest="command", required=True)

    preview = sub.add_parser("preview")
    preview.add_argument("--signals", type=Path, required=True)

    dig = sub.add_parser("digest")
    dig.add_argument("--signals", type=Path, required=True)
    dig.add_argument("--channel", default="oncall-ops")

    args = parser.parse_args(argv)
    formatter = SummaryFormatter({args.origin})
    router = AlertRouter(formatter, args.origin, args.outbox)
    raw = json.loads(args.signals.read_text(encoding="utf-8"))
    signals = [IncidentSignal(**entry) for entry in raw]
    router.ingest_signals(signals)

    if args.command == "preview":
        top = router.dedup.top_incidents(limit=5)
        print(json.dumps([item.__dict__ for item in top], sort_keys=True))
        return 0
    if args.command == "digest":
        out = router.dispatch_digest(channel=args.channel)
        print(json.dumps({"written": str(out)}))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
