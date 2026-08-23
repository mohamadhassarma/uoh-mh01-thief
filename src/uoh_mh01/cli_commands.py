"""The `selftest` and `peer` CLI command bodies. Split out of __main__.py
purely to keep that file under the project's ~150-line budget.
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

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "game.json"


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
    toml_path = args.peer_config or (REPO_ROOT / "config" / role.value / "game.toml")

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

    out_dir = args.log_dir or (REPO_ROOT / "logs")

    from .infra.negotiation import NegotiationRefusedError
    from .infra.series import run_series
    from .shared.build_commit import DirtyWorkingTreeError

    print(f"Playing a {config.network.num_games}-sub-game series, role alternating (natural role: {role.value})...")
    print()

    try:
        summaries = asyncio.run(
            run_series(role, config, peer_config, seed=args.seed, out_dir=str(out_dir), counted=args.counted)
        )
    except DirtyWorkingTreeError as exc:
        print("REFUSED before the handshake - nothing was played:")
        print(f"  {exc}")
        return 2
    except NegotiationRefusedError as exc:
        print("Handshake REFUSED — the series never started playing:")
        print(f"  {exc}")
        return 2

    for summary in summaries:
        print(f"--- Sub-game {summary['sub_game_number']} (playing {summary['role']}) ---")
        if "undefined_outcome" in summary:
            print(f"  UNDEFINED: {summary['undefined_outcome']}")
        elif "disputed" in summary:
            print(f"  DISPUTED: mine={summary['disputed']['mine']!r} theirs={summary['disputed']['theirs']!r}")
        else:
            print(f"  Terminal condition: {summary['terminal_condition']}")
            print(f"  Score — police: {summary['police_score']}, thief: {summary['thief_score']}")
        # Only MY verdict on THEM exists: with an ack-only wire the opponent's
        # verdict on me never crosses back (docs/WIRE.md §5).
        print(f"  Audit of opponent by me: {summary['audit_of_opponent_by_me']}")
    print(f"\nArtifacts written to: {out_dir}")
    return 0


def _report_counted_series(args, config, peer_config, summaries, out_dir) -> None:
    """Book §9.3: at the end of a counted series the agent mails its own report,
    with no human step. A friendly sends nothing to anyone.

    Deliberately not fatal. The games were played and their artifacts are on
    disk; a failed send is recoverable with `report --counted`, whereas
    crashing here would lose the printed summary of a series that really
    happened.
    """
    if not getattr(args, "counted", False) or not summaries:
        return
    from .report import auto_send

    print()
    print("COUNTED series complete - sending the report automatically (book section 9.3)...")
    outcome = auto_send.send_counted_series(
        Path(out_dir), summaries[0]["game_id"], config, own_group_id=peer_config.group_id
    )
    if outcome.sent:
        print(f"  sent to the lecturer (gmail message id {outcome.message_id})")
        return
    print(f"  NOT SENT: {outcome.reason}")
    for blocker in outcome.blockers:
        print(f"    - {blocker}")
    print("  The artifacts are on disk. Fix the cause, then use the manual fallback:")
    print(f"    uoh-mh01 report --game-id {summaries[0]['game_id']} --counted")
