"""CLI entry point: `python -m uoh_mh01 <command>`.

`selftest` (stage 1) plays one full match locally, in a single process, with
placeholder move selection. `peer` (stage 2) starts this side as an
independent MCP peer process, talking to an opponent process over
localhost.
"""

from __future__ import annotations

import argparse
import asyncio
import random
import sys
from pathlib import Path

from .domain.config import ConfigError, load_config
from .domain.match import FIRST_MOVER, MatchResult, UndefinedOutcomeError, run_match
from .domain.state import Side
from .domain.strategies import make_random_strategy
from .shared.peer_config import PeerConfigError, load_peer_config

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_CONFIG_PATH = _REPO_ROOT / "config" / "game.json"


def _format_log(result: MatchResult) -> str:
    lines = []
    for entry in result.final_state.move_log:
        capture_note = ""
        if entry.capture_triggered:
            claim = "claimed by police" if entry.capture_claimed_by_police else "detected, unclaimed"
            capture_note = f"  <-- CAPTURE ({claim})"
        lines.append(
            f"  turn {entry.turn_number:>3} | {entry.actor.value:<6} | {entry.action_type.value:<7} "
            f"{entry.detail:<6} | cop={entry.resulting_cop_pos} thief={entry.resulting_thief_pos}{capture_note}"
        )
    return "\n".join(lines)


def cmd_selftest(args: argparse.Namespace) -> int:
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2

    rng = random.Random(args.seed)
    police_strategy = make_random_strategy(rng)
    thief_strategy = make_random_strategy(rng)

    print(f"Loaded config from: {args.config}")
    print(f"grid_size={config.board.grid_size} cop_start={config.board.cop_start} "
          f"thief_start={config.board.thief_start} first_mover={FIRST_MOVER.value} seed={args.seed}\n")

    try:
        result = run_match(config, police_strategy, thief_strategy)
    except UndefinedOutcomeError as exc:
        print("Match ended in an UNDEFINED state (not a crash — a known open rules question):")
        print(f"  {exc}\n")
        print("Move log up to that point:")
        # UndefinedOutcomeError carries no state; re-run is not attempted here
        # because move selection is randomized. See PRD-01 "Open questions".
        return 1

    print("Move log:")
    print(_format_log(result))
    print()
    print(f"Terminal condition: {result.terminal_condition.value}")
    if result.offending_side is not None:
        print(f"Offending side: {result.offending_side.value}")
    print(f"Final score — police: {result.police_score}, thief: {result.thief_score}")
    return 0


def cmd_peer(args: argparse.Namespace) -> int:
    role = Side(args.role)
    toml_path = args.peer_config or (_REPO_ROOT / "config" / role.value / "game.toml")

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2

    try:
        peer_config = load_peer_config(role.value, toml_path, args.config)
    except PeerConfigError as exc:
        print(f"peer config error: {exc}", file=sys.stderr)
        return 2

    strategy = make_random_strategy(random.Random(args.seed))

    print(f"Role:            {role.value}")
    print(f"Group:           {peer_config.group_name} ({peer_config.group_id})")
    print(f"Listening on:    127.0.0.1:{peer_config.my_port}")
    print(f"Opponent URL:    {peer_config.opponent_url}")
    print(f"First mover:     {FIRST_MOVER.value}")
    print(f"response_timeout_sec={config.network.response_timeout_sec} "
          f"watchdog_timeout_sec={config.network.watchdog_timeout_sec} "
          f"turn_timeout_seconds={peer_config.turn_timeout_seconds}")
    print("Waiting for opponent..." if role is not FIRST_MOVER else "Starting — I move first.")
    print()

    log_path = args.log or (_REPO_ROOT / "logs" / f"{role.value}_match.json")

    from .infra.outcomes import DisputedOutcomeError
    from .orchestrator import run_peer

    try:
        outcome = asyncio.run(run_peer(role, config, peer_config, strategy=strategy, log_path=str(log_path)))
    except UndefinedOutcomeError as exc:
        print("Match ended in an UNDEFINED state (not a crash — a known open rules question):")
        print(f"  {exc}")
        print(f"Partial log written to: {log_path}")
        return 1
    except DisputedOutcomeError as exc:
        print("Match ended in DISAGREEMENT — my own recomputation and the opponent's claim differ:")
        print(f"  mine={exc.mine!r} theirs={exc.theirs!r}")
        print("Never auto-resolved (see PRD-02 'Stage 2 corrections' B1) — the mutual audit in a")
        print("later stage is the rulebook's answer. Both sides' logs record both claims.")
        print(f"Partial log written to: {log_path}")
        return 1

    print(f"Terminal condition: {outcome.terminal_condition.value}")
    if outcome.offending_side is not None:
        print(f"Offending side: {outcome.offending_side.value}")
    print(f"Final score — police: {outcome.police_score}, thief: {outcome.thief_score}")
    print(f"Log written to: {log_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="uoh_mh01")
    subparsers = parser.add_subparsers(dest="command", required=True)

    selftest = subparsers.add_parser("selftest", help="Play one full match locally with placeholder move selection")
    selftest.add_argument("--config", type=Path, default=_DEFAULT_CONFIG_PATH, help="Path to game.json")
    selftest.add_argument("--seed", type=int, default=42, help="RNG seed for reproducible placeholder play")
    selftest.set_defaults(func=cmd_selftest)

    peer = subparsers.add_parser("peer", help="Start this side as an independent MCP peer process")
    peer.add_argument("--role", choices=["police", "thief"], required=True)
    peer.add_argument("--config", type=Path, default=_DEFAULT_CONFIG_PATH, help="Path to the signed config/game.json")
    peer.add_argument("--peer-config", type=Path, default=None, help="Path to config/<role>/game.toml (default: derived from --role)")
    peer.add_argument("--log", type=Path, default=None, help="Path to write the match log (default: logs/<role>_match.json)")
    peer.add_argument("--seed", type=int, default=None, help="RNG seed for reproducible placeholder move selection")
    peer.set_defaults(func=cmd_peer)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
