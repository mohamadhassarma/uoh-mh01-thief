"""CLI entry point: `python -m uoh_mh01 <command>`.

Stage 1 only implements `selftest` — playing one full match locally with
placeholder move selection, to prove the engine runs end-to-end. Real
peer-to-peer play is stage 2+.
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

from .domain.config import ConfigError, load_config
from .domain.match import FIRST_MOVER, MatchResult, UndefinedOutcomeError, run_match
from .domain.strategies import make_random_strategy

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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="uoh_mh01")
    subparsers = parser.add_subparsers(dest="command", required=True)

    selftest = subparsers.add_parser("selftest", help="Play one full match locally with placeholder move selection")
    selftest.add_argument("--config", type=Path, default=_DEFAULT_CONFIG_PATH, help="Path to game.json")
    selftest.add_argument("--seed", type=int, default=42, help="RNG seed for reproducible placeholder play")
    selftest.set_defaults(func=cmd_selftest)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
