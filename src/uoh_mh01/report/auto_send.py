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

    if counted:
        existing = ledger.find(game_uid, path=ledger_path)
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

    blockers = blocking_reasons(result, ledger_path=ledger_path if counted else None)
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
    if counted:
        _record(result, opponent, ledger.STATUS_SENDING, ledger_path)
    try:
        sent = pipeline.send_report(path, result, config, counted=counted, sender=sender, to=to, service=service)
    except Exception as exc:  # noqa: BLE001 - recorded, then surfaced to the operator
        if counted:
            _record(result, opponent, ledger.STATUS_FAILED, ledger_path, detail=str(exc)[:300])
        logger.error("automatic report send FAILED: %s", exc)
        return AutoSendOutcome(
            sent=False, reason=f"send failed: {exc}", result_path=path, game_uid=game_uid, counted=counted
        )

    if counted:
        _record(result, opponent, ledger.STATUS_SENT, ledger_path)
    logger.info("report sent for %s (message id %s)", game_id, sent.get("id"))
    return AutoSendOutcome(
        sent=True,
        result_path=path,
        message_id=sent.get("id"),
        game_uid=game_uid,
        counted=counted,
        recipient=to,
    )


def _record(
    result: dict[str, Any], opponent: str | None, status: str, path: Path, *, detail: str | None = None
) -> None:
    ledger.record_counted_series(
        opponent_group_id=opponent or "unknown",
        game_id=result["game_id"],
        game_uid=result["game_uid"],
        ended_at=result["sub_games"][-1]["ended_at"],
        status=status,
        detail=detail,
        path=path,
    )
