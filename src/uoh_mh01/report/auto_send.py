"""Automatic end-of-series reporting (book §9.3).

THE REQUIREMENT, verbatim: "בתום כל משחק חוקי מול קבוצה יריבה, אין עוד מקום
להתערבות אנושית בדיווח. כל אחת משתי הקבוצות מתוכנתת לשלוח בעצמה — כל קבוצה
בנפרד — הודעת סיכום אוטומטית אל המרצה באמצעות Gmail API; אין די בכך שצד אחד
בלבד ישלח." — at the end of every legal game there is no more room for human
intervention in reporting; each group's agent mails its own summary, and one
side sending is not enough. A manual `report --counted` step does not satisfy
this, which is why this module exists.

THE SAME PARAGRAPH NAMES THE DANGER: automation is "ברכה ומלכודת כאחת", a
blessing and a trap, because it hands a live mail account to code that may
contain a bug — "מה קורה כאשר לולאה אינסופית מתחילה לירות אלפי הודעות לדקה?"
So §9.3.1 introduces the Gatekeeper in the very next breath, and every send
here goes through it. Three independent things hold the line:

  * the LEDGER, which records a row BEFORE the send and refuses a second
    attempt on the same `game_uid`,
  * the GATEKEEPER's token bucket, quota and circuit breaker,
  * the REFUSAL rules below, which stop a bad report from going out at all.

An automatic send has nobody watching it. That inverts the usual bias: where a
human operator would be shown a warning and left to judge, this refuses.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..domain.config import GameConfig
from . import ledger, pipeline
from .result_artifact import missing_mandatory_fields

logger = logging.getLogger(__name__)


# Statuses that stop another attempt. `failed` is absent on purpose — see the
# comment at the check itself.
BLOCKING_STATUSES = frozenset({ledger.STATUS_SENT, ledger.STATUS_SENDING})


@dataclass
class AutoSendOutcome:
    sent: bool
    reason: str | None = None
    blockers: list[str] = field(default_factory=list)
    result_path: Path | None = None
    message_id: str | None = None
    game_uid: str | None = None
    counted: bool = True
    recipient: str | None = None
    attempt: int = 1


def blocking_reasons(result: dict[str, Any], *, ledger_path: Path | None) -> list[str]:
    """Everything that must be true before a report may leave, in one place so
    the automatic path and the manual fallback cannot drift.

    `ledger_path=None` for a friendly: the duplicate-send interlock is about
    counted evidence, and a practice report may legitimately be sent twice.
    """
    reasons = []
    if not result["mutual_agreement"]["confirmed"]:
        failed = [row["sub_game_number"] for row in result["sub_games"] if not row["audit"]["log_verified"]]
        reasons.append(f"the mutual audit did not confirm sub-game(s) {failed}")
    reasons.extend(missing_mandatory_fields(result))
    if ledger_path is not None and ledger.already_reported(result["game_uid"], path=ledger_path):
        reasons.append(f"a report for game_uid {result['game_uid']} was already sent (ledger)")
    return reasons


def correction_refusals(reason: str, *, counted: bool, superseded: dict[str, Any] | None) -> list[str]:
    """When a DECLARED CORRECTION is allowed to pass the duplicate-send
    interlock, and nothing else.

    The interlock exists because an automatic sender holding live mail
    credentials must not be able to mail the lecturer twice for one series.
    A correction is the one case where a second send is intended - a human has
    decided the first report was wrong and is saying so on the record. Every
    condition below keeps that narrow:

      * COUNTED only. A friendly never touches the ledger, so there is nothing
        for a correction to mean there.
      * A REASON is mandatory and goes in the ledger. An unexplained second
        send is indistinguishable from the runaway loop the interlock is for.
      * There must ALREADY BE A DELIVERED SEND to supersede. This is what stops
        the flag being a general bypass: with no `sent` row it refuses, so it
        can never turn a first send into an unguarded one.
      * A `sending` row is NOT correctable. That row means a send whose fate is
        unknown - it may have been delivered. Correcting a send that may not
        have happened is a guess, and the interlock's whole job is to stop
        guesses becoming a second mail to the lecturer.
    """
    problems = []
    if not counted:
        problems.append("a correction re-submits a COUNTED report to the lecturer; use --counted")
    if not reason.strip():
        problems.append("a correction must state its reason - it is recorded in the ledger")
    if superseded is None:
        problems.append("there is no earlier send for this series to correct")
    elif superseded.get("status") != ledger.STATUS_SENT:
        problems.append(
            f"the ledger's latest row for this series is {superseded.get('status')!r}, not "
            f"{ledger.STATUS_SENT!r} - there is no delivered report to supersede"
        )
    return problems


def send_counted_series(
    logs_dir: Path,
    game_id: str,
    config: GameConfig,
    *,
    own_group_id: str,
    counted: bool = True,
    sender: str = "me",
    ledger_path: Path = ledger.LEDGER_PATH,
    to: str | None = None,
    correction: str | None = None,
    service: Any = None,
) -> AutoSendOutcome:
    """Build, check, and mail this series' report. Called by the peer process
    itself at the end of a series — never by a human.

    ONE path, two recipients. A counted series mails the lecturer; a friendly
    mails `to`, or nothing at all if `to` is absent. Everything else — the
    build, the refusal rules, the Gatekeeper — is the same code either way, so
    a friendly send genuinely exercises the counted one.

    The single asymmetry is the LEDGER, and it is forced: `league/` is
    committed evidence of counted play, and a warm-up row there would make the
    next real series against that opponent declare `first_meeting_between_
    groups` wrongly — a rules-37/38 false declaration produced by accident,
    which App. E rule 35 would charge to the innocent opponent too. So a
    friendly writes no row and gets no duplicate-send interlock; its protection
    against a runaway loop is the Gatekeeper, which it shares.
    """
    result = pipeline.build(logs_dir, game_id, config, ledger_path=ledger_path)
    path = pipeline.write(result, logs_dir)
    game_uid = result["game_uid"]

    superseded = ledger.find(game_uid, path=ledger_path) if counted else None
    attempt = 1
    if correction is not None:
        problems = correction_refusals(correction, counted=counted, superseded=superseded)
        if problems:
            logger.error("REFUSING the declared correction: %s", "; ".join(problems))
            return AutoSendOutcome(
                sent=False,
                reason="this is not a valid declared correction",
                blockers=problems,
                result_path=path,
                game_uid=game_uid,
                counted=counted,
            )
        attempt = ledger.next_attempt(game_uid, path=ledger_path)

    if counted and correction is None:
        existing = superseded
        if existing is not None and existing.get("status") in BLOCKING_STATUSES:
            # `sent` is obvious. `sending` covers a row stranded by a process
            # killed mid-send: a missed send is recoverable by hand, a duplicate
            # is not recallable, so an in-flight-looking row is the safe side.
            #
            # `failed` deliberately does NOT block. Nothing was delivered, and
            # retrying is exactly what the manual fallback exists for — a failed
            # row that blocked every retry would make that documented path
            # impossible.
            reason = f"the ledger already holds a {existing.get('status')!r} row for game_uid {game_uid}"
            logger.warning("NOT auto-sending: %s", reason)
            return AutoSendOutcome(sent=False, reason=reason, result_path=path, game_uid=game_uid, counted=counted)

    # A correction skips the duplicate-send blocker and NOTHING else: a failed
    # audit or a missing mandatory field still stops it. A correction that is
    # itself unfit is not a correction.
    check_duplicates = counted and correction is None
    blockers = blocking_reasons(result, ledger_path=ledger_path if check_duplicates else None)
    if blockers:
        logger.error("NOT auto-sending the report — %s blocker(s): %s", len(blockers), "; ".join(blockers))
        return AutoSendOutcome(
            sent=False,
            reason="the report is not fit to send",
            blockers=blockers,
            result_path=path,
            game_uid=game_uid,
            counted=counted,
        )

    opponent = next((g for g in result["groups"] if g != own_group_id), None)
    corrects = ledger.attempt_of(superseded) if (correction is not None and superseded) else None
    if counted:
        _record(result, opponent, ledger.STATUS_SENDING, ledger_path,
                attempt=attempt, correction_of=corrects, correction_reason=correction)
    try:
        sent = pipeline.send_report(path, result, config, counted=counted, sender=sender, to=to, service=service)
    except Exception as exc:  # noqa: BLE001 - recorded, then surfaced to the operator
        if counted:
            _record(result, opponent, ledger.STATUS_FAILED, ledger_path, detail=str(exc)[:300],
                    attempt=attempt, correction_of=corrects, correction_reason=correction)
        logger.error("automatic report send FAILED: %s", exc)
        return AutoSendOutcome(
            sent=False, reason=f"send failed: {exc}", result_path=path, game_uid=game_uid, counted=counted
        )

    if counted:
        _record(result, opponent, ledger.STATUS_SENT, ledger_path, detail=f"gmail message id {sent.get('id')}",
                attempt=attempt, correction_of=corrects, correction_reason=correction)
    logger.info("report sent for %s (message id %s)", game_id, sent.get("id"))
    return AutoSendOutcome(
        sent=True,
        result_path=path,
        message_id=sent.get("id"),
        game_uid=game_uid,
        counted=counted,
        recipient=to,
        attempt=attempt,
    )


def _record(
    result: dict[str, Any],
    opponent: str | None,
    status: str,
    path: Path,
    *,
    detail: str | None = None,
    attempt: int = 1,
    correction_of: int | None = None,
    correction_reason: str | None = None,
) -> None:
    ledger.record_counted_series(
        opponent_group_id=opponent or "unknown",
        game_id=result["game_id"],
        game_uid=result["game_uid"],
        ended_at=result["sub_games"][-1]["ended_at"],
        status=status,
        detail=detail,
        attempt=attempt,
        correction_of=correction_of,
        correction_reason=correction_reason,
        path=path,
    )
