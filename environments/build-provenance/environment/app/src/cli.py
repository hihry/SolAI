"""CLI entrypoint for build-provenance."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .manifest import BuildStage
from .merkle import MerkleTree
from .pipeline import ProvenancePipeline


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="build-provenance")
    sub = parser.add_subparsers(dest="command", required=True)

    root_cmd = sub.add_parser("merkle-root")
    root_cmd.add_argument("--artifacts", type=Path, required=True)

    ver_cmd = sub.add_parser("verify")
    ver_cmd.add_argument("--chain", type=Path, required=True)
    ver_cmd.add_argument("--key-hex", required=True)

    args = parser.parse_args(argv)
    if args.command == "merkle-root":
        items = json.loads(args.artifacts.read_text(encoding="utf-8"))
        print(json.dumps({"root": MerkleTree.compute_root(items)}))
        return 0
    if args.command == "verify":
        raw_stages = json.loads(args.chain.read_text(encoding="utf-8"))
        stages = [BuildStage(**entry) for entry in raw_stages]
        pipeline = ProvenancePipeline(bytes.fromhex(args.key_hex))
        audits = pipeline.verify_chain(stages)
        print(json.dumps({"passed": all(a.passed for a in audits), "stages": [a.__dict__ for a in audits]}))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
