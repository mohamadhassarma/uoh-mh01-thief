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


def _recipient_modes(parser: argparse.ArgumentParser, *, counted_help: str) -> None:
    """The report's two mutually exclusive destinations.

    `--counted` is NOT a boolean convenience. Without it the recipient resolves
    to an address that cannot be delivered at all, so a warm-up has nowhere to
    go even if every other check were bypassed (PRD-07).

    `--to` is the friendly destination and the way to exercise the real
    automatic path without submitting anything. It is refused alongside
    `--counted` here, at parse time, because the alternative is discovering the
    conflict after a full counted series has been played out.
    """
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--counted", action="store_true", help=counted_help)
    modes.add_argument("--to", default=None, help="FRIENDLY: mail the report to this address instead (never the lecturer)")


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
    # Both modes run the same automatic §9.3 send at the end of the series and
    # differ only in the recipient, so they are mutually exclusive by
    # construction: argparse refuses the pair before a single sub-game is
    # played, rather than after a whole series has been spent.
    _recipient_modes(peer, counted_help="This series is COUNTED: mail the report to the lecturer (requires a clean tree)")
    peer.set_defaults(func=cmd_peer)

    report = subparsers.add_parser("report", help="Build result_<game_id>.json from a played series (PRD-07)")
    report.add_argument("--game-id", required=True, help="e.g. their-group-vs-uoh-mh01")
    report.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH, help="Path to the signed config/game.json")
    report.add_argument("--log-dir", type=Path, default=None, help="Where the series artifacts live (default: logs/)")
    report.add_argument("--group-id", default="uoh-mh01", help="This group's id, used to identify the opponent")
    report.add_argument("--sender", default="me", help="The From address for the report mail")
    _recipient_modes(report, counted_help="This is a COUNTED series: mail it to the lecturer")
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
