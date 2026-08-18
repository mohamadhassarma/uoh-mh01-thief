"""CLI entry point: `python -m uoh_mh01 <command>`.

`selftest` (stage 1) plays one full match locally, in a single process, with
placeholder move selection. `peer` (stage 2) starts this side as an
independent MCP peer process, talking to an opponent process over
localhost.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from .cli_commands import DEFAULT_CONFIG_PATH, cmd_peer, cmd_selftest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="uoh_mh01")
    subparsers = parser.add_subparsers(dest="command", required=True)

    selftest = subparsers.add_parser("selftest", help="Play one full match locally with placeholder move selection")
    selftest.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH, help="Path to game.json")
    selftest.add_argument("--seed", type=int, default=42, help="RNG seed for reproducible placeholder play")
    selftest.set_defaults(func=cmd_selftest)

    peer = subparsers.add_parser("peer", help="Start this side as an independent MCP peer process")
    peer.add_argument("--role", choices=["police", "thief"], required=True)
    peer.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH, help="Path to the signed config/game.json")
    peer.add_argument("--peer-config", type=Path, default=None, help="Path to config/<role>/game.toml (default: derived from --role)")
    peer.add_argument("--log-dir", type=Path, default=None, help="Directory to write the series' JSON artifacts into (default: logs/)")
    peer.add_argument("--seed", type=int, default=None, help="RNG seed for reproducible placeholder move selection")
    peer.set_defaults(func=cmd_peer)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
