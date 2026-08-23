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
    """Every send from here goes through `auto_send.send_counted_series` — the
    same entry point the peer process uses at the end of a series.

    There is deliberately no second implementation. An earlier version had one,
    and it wrote its own ledger row without the status the duplicate-send check
    reads, so a repeat manual send would not have been blocked at all.
    """
    if args.counted and not args.to:
        _fallback_banner()
    elif args.to:
        _rehearsal_banner(args.counted, args.to)

    outcome = auto_send.send_counted_series(
        Path(args.log_dir or "logs"),
        result["game_id"],
        config,
        own_group_id=args.group_id,
        counted=args.counted,
        sender=args.sender,
        to=args.to,
    )
    if outcome.sent:
        print(f"sent to {outcome.recipient or LECTURER_REPORT_ADDRESS} (gmail message id {outcome.message_id})")
        if outcome.rehearsal:
            print("REHEARSAL ONLY - the lecturer received nothing and the league ledger is untouched.")
        return 0
    print(f"\nNOT SENT: {outcome.reason}", file=sys.stderr)
    for blocker in outcome.blockers:
        print(f"  - {blocker}", file=sys.stderr)
    return 3


def _fallback_banner() -> None:
    """Book §9.3 requires the peer process to send its own report with no human
    step, so reaching a real submission by hand means the automatic send did
    not happen — say so loudly rather than letting it look like the normal
    route."""
    print("\n" + "=" * 72, file=sys.stderr)
    print("MANUAL FALLBACK: book section 9.3 requires the peer process to send this", file=sys.stderr)
    print("report automatically at the end of a counted series. You are sending it by", file=sys.stderr)
    print("hand, which means the automatic send did not happen. Worth finding out why.", file=sys.stderr)
    print("=" * 72, file=sys.stderr)


def _rehearsal_banner(counted: bool, to: str) -> None:
    kind = "COUNTED" if counted else "FRIENDLY"
    print("\n" + "*" * 72)
    print(f"REHEARSAL - this is NOT a submission. {kind} report, --to {to}")
    print("The full automatic path runs (auto_send, Gatekeeper, ledger interlock),")
    print("but delivery goes to the address above and NOT to the lecturer, and the")
    print("committed league ledger is not written. Nothing here counts for grading.")
    print("*" * 72)


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
