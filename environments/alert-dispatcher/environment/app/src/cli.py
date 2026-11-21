"""CLI entrypoint for alert-dispatcher."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .formatter import SummaryFormatter
from .incidents import IncidentSignal
from .router import AlertRouter, ingest_silences
from .standin import LocalWebhookStandIn

DEFAULT_ORIGIN = "https://status.internal.example"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="alert-dispatcher")
    parser.add_argument("--outbox", type=Path, required=True)
    parser.add_argument("--origin", default=DEFAULT_ORIGIN)
    parser.add_argument("--allowed-origin", action="append", default=None)
    parser.add_argument("--silences", type=Path, default=None)
    parser.add_argument("--standin-dir", type=Path, default=None)
    sub = parser.add_subparsers(dest="command", required=True)

    preview = sub.add_parser("preview")
    preview.add_argument("--signals", type=Path, required=True)

    dig = sub.add_parser("digest")
    dig.add_argument("--signals", type=Path, required=True)
    dig.add_argument("--channel", default="oncall-ops")
    dig.add_argument("--max-items", type=int, default=10)
    dig.add_argument("--webhook-url", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    allowed = set(args.allowed_origin) if args.allowed_origin else {DEFAULT_ORIGIN}
    formatter = SummaryFormatter(allowed)
    formatter.build_status_url(args.origin, "origin-check")

    silences = ingest_silences(json.loads(args.silences.read_text(encoding="utf-8"))) if args.silences else None
    standin = LocalWebhookStandIn(args.standin_dir) if args.standin_dir else None
    router = AlertRouter(
        formatter, args.origin, args.outbox, silences=silences,
        standin=standin, webhook_url=getattr(args, "webhook_url", None),
    )
    signals = [IncidentSignal.from_dict(e) for e in json.loads(args.signals.read_text(encoding="utf-8"))]
    router.ingest_signals(signals)

    if args.command == "preview":
        top = router.dedup.top_incidents(limit=5)
        print(json.dumps([item.__dict__ for item in top], sort_keys=True))
        return 0
    if args.command == "digest":
        out = router.dispatch_digest(channel=args.channel, max_items=args.max_items)
        print(json.dumps({"written": str(out), "channel": args.channel, "max_items": args.max_items}))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
