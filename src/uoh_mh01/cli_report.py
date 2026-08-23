"""`report` and `authorize-gmail` - the PRD-07 command surface.

`report` builds and writes `result_<game_id>.json` from artifacts already on
disk. It mails that file ONLY under `--counted`, and mailing is the sole path
that advances the counted-games ledger, so the report and the ledger can never
disagree about whether a series counted.
"""

from __future__ import annotations

import sys
from pathlib import Path

from .domain.config import load_config
from .infra.gmail_sender import LECTURER_REPORT_ADDRESS
from .report import ledger, pipeline
from .report.result_artifact import verify_mutual_agreement


def cmd_report(args) -> int:
    config = load_config(args.config)
    logs_dir = Path(args.log_dir or "logs")
    try:
        result = pipeline.build(logs_dir, args.game_id, config)
    except Exception as exc:  # noqa: BLE001 - a CLI must print, not traceback
        print(f"could not build the report: {exc}", file=sys.stderr)
        return 2

    path = pipeline.write(result, logs_dir)
    final = result["final_result"]
    print(f"wrote {path}")
    print(f"  game_uid        {result['game_uid']}")
    print(f"  sub-games       {result['num_sub_games']}")
    print(f"  total_score     {final['total_score']}")
    print(f"  winner_group    {final['winner_group']}  (tie rule: {final['tie_rule']})")
    print(f"  tokens_total    {final['tokens_total_series']}")
    print(f"  first_meeting   {final['first_meeting_between_groups']}")
    print(f"  audits verified {result['mutual_agreement']['confirmed']}")
    print(f"  consensus       {result['mutual_agreement']['sha256']}")
    print(f"  self-verifies   {verify_mutual_agreement(result)}")
    _warn_on_missing_mandatory_fields(result)

    if not args.counted and not args.to:
        print("\nNOT SENT: a warm-up with no --to has nowhere to go. Use --to <address> to exercise")
        print("the real send path, or --counted (with no --to) to submit a genuinely counted series.")
        return 0
    return _send(path, result, config, args)


def _send(path: Path, result: dict, config, args) -> int:
    # A failed audit blocks only a COUNTED submission. A practice send to your
    # own address is exactly how you would want to inspect a broken report.
    if args.counted and not result["mutual_agreement"]["confirmed"]:
        print("\nREFUSING TO SEND: at least one sub-game's audit did not pass.", file=sys.stderr)
        return 3
    try:
        sent = pipeline.send_report(
            path, result, config, counted=args.counted, sender=args.sender, to=args.to
        )
    except Exception as exc:  # noqa: BLE001 - a CLI must print, not traceback
        print(f"\nsend failed: {exc}", file=sys.stderr)
        return 4
    # Only a COUNTED send advances the ledger. A practice send to --to must
    # never register as a played counted series (App. E rules 37/38).
    opponent = next(g for g in result["groups"] if g != args.group_id) if args.group_id else None
    if args.counted and opponent:
        ledger.record_counted_series(
            opponent_group_id=opponent,
            game_id=result["game_id"],
            game_uid=result["game_uid"],
            ended_at=result["sub_games"][-1]["ended_at"],
        )
        print(f"ledger advanced: counted series against {opponent}")
    print(f"sent to {args.to or LECTURER_REPORT_ADDRESS} (gmail message id {sent.get('id')})")
    return 0


def _warn_on_missing_mandatory_fields(result: dict) -> None:
    """Book §9 makes three things mandatory. Say so loudly rather than mailing
    a quietly incomplete report."""
    missing = []
    if "github" not in result["links"]:
        missing.append("links.github (both groups' repo links)")
    for row in result["sub_games"]:
        absent = [gid for gid, commit in row["github_commit"].items() if not commit]
        if absent:
            missing.append(f"github_commit for {absent} in sub-game {row['sub_game_number']}")
    if missing:
        print("\n  ! book section 9 mandatory fields not fully populated:")
        for item in missing:
            print(f"      - {item}")


def cmd_authorize_gmail(args) -> int:
    from .infra.gmail_auth import authorize

    print("Opening the Google consent screen - approve the send-only scope.")
    try:
        token = authorize(Path(args.secrets_dir) if args.secrets_dir else None)
    except Exception as exc:  # noqa: BLE001 - a CLI must print, not traceback
        print(f"authorization failed: {exc}", file=sys.stderr)
        return 2
    print(f"wrote {token}")
    return 0
