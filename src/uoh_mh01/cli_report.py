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
from .report import auto_send, pipeline
from .report.result_artifact import missing_mandatory_fields, verify_mutual_agreement


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
    if args.counted:
        return _manual_fallback(result, config, args)
    # A PRACTICE send: not counted, never the lecturer, never the ledger. The
    # blocking rules deliberately do not apply — inspecting a broken report by
    # mailing it to yourself is exactly what practice is for.
    try:
        sent = pipeline.send_report(path, result, config, counted=False, sender=args.sender, to=args.to)
    except Exception as exc:  # noqa: BLE001 - a CLI must print, not traceback
        print(f"\nsend failed: {exc}", file=sys.stderr)
        return 4
    print(f"sent to {args.to} (gmail message id {sent.get('id')})")
    return 0


def _manual_fallback(result: dict, config, args) -> int:
    """`report --counted` is the FALLBACK path, and it routes through the SAME
    `auto_send.send_counted_series` the peer process uses.

    Book §9.3 requires the agent to mail its own report with no human step, so
    reaching here by hand means the automatic send did not happen — say so
    loudly rather than letting a manual send look like the normal route. Going
    through one shared entry point is what makes the ledger interlock
    universal: an earlier version wrote the ledger row itself, from here, and
    that row was missing the status the duplicate-send check reads, so a second
    manual send would not have been blocked at all.
    """
    print("\n" + "=" * 72, file=sys.stderr)
    print("MANUAL FALLBACK: book section 9.3 requires the peer process to send this", file=sys.stderr)
    print("report automatically at the end of a counted series. You are sending it by", file=sys.stderr)
    print("hand, which means the automatic send did not happen. Worth finding out why.", file=sys.stderr)
    print("=" * 72, file=sys.stderr)

    outcome = auto_send.send_counted_series(
        Path(args.log_dir or "logs"), result["game_id"], config, own_group_id=args.group_id, sender=args.sender
    )
    if outcome.sent:
        print(f"sent to {LECTURER_REPORT_ADDRESS} (gmail message id {outcome.message_id})")
        return 0
    print(f"\nNOT SENT: {outcome.reason}", file=sys.stderr)
    for blocker in outcome.blockers:
        print(f"  - {blocker}", file=sys.stderr)
    return 3


def _warn_on_missing_mandatory_fields(result: dict) -> None:
    """Book section 9's mandatory items. The automatic path REFUSES on these;
    here they are only a warning, because a human is looking at the output and
    a practice send of an incomplete report is a legitimate thing to want."""
    missing = missing_mandatory_fields(result)
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
