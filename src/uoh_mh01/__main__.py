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
from .cli_report import cmd_authorize_gmail, cmd_report


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
    # A counted series REFUSES to start on a dirty tree; a friendly only warns
    # (book ch.5 / App. E rules 37/38 — see shared/build_commit.py).
    peer.add_argument("--counted", action="store_true", help="This series is COUNTED: refuse to start unless the tree is clean")
    # REHEARSAL. Runs the full automatic §9.3 send at series end and delivers
    # to this address instead of the lecturer. Works with or without --counted;
    # never accepts the lecturer's own mailbox.
    peer.add_argument("--to", default=None, help="Rehearse the automatic send, delivering to this address")
    peer.set_defaults(func=cmd_peer)

    report = subparsers.add_parser("report", help="Build result_<game_id>.json from a played series (PRD-07)")
    report.add_argument("--game-id", required=True, help="e.g. their-group-vs-uoh-mh01")
    report.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH, help="Path to the signed config/game.json")
    report.add_argument("--log-dir", type=Path, default=None, help="Where the series artifacts live (default: logs/)")
    report.add_argument("--group-id", default="uoh-mh01", help="This group's id, used to identify the opponent")
    report.add_argument("--sender", default="me", help="The From address for the report mail")
    # NOT a boolean convenience. Without it the recipient resolves to an
    # address that cannot be delivered at all, so a warm-up has nowhere to go
    # even if every other check were bypassed (PRD-07).
    report.add_argument("--counted", action="store_true", help="This is a COUNTED series: mail it to the lecturer")
    # Exercising the real send path without submitting. Refused together with
    # --counted: a counted report going anywhere but the lecturer is a lost game.
    report.add_argument("--to", default=None, help="REHEARSAL: run the full automatic path, deliver here instead of the lecturer")
    report.set_defaults(func=cmd_report)

    authorize = subparsers.add_parser("authorize-gmail", help="Run the OAuth consent flow once (opens a browser)")
    authorize.add_argument("--secrets-dir", default=None, help="Default: the repo-external secrets directory")
    authorize.set_defaults(func=cmd_authorize_gmail)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
