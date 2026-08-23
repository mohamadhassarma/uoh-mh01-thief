"""Mailing `result_<game_id>.json` to the lecturer (book §9 + Appendix A).

THE ATTACHMENT IS NOT OPTIONAL, AND THE BOOK CONTRADICTS ITSELF ABOUT IT.
§9 is unambiguous: "דיווח חייב להיות JSON מובנה ... הנשלח כקובץ מצורף. כל
ניסיון לשלוח דיווח פתוח בטקסט חופשי (plaintext) ... יוביל לדחיית הדיווח" —
the report MUST be an attached file, and a free-text body is REJECTED, with
the round's league points at risk. Appendix A's own worked listing then builds
`MIMEText(body)` — a plain-text body with no attachment at all — and the
reference implementation's `email_sender.py` does the same via `--body`.

Rather than pick a side of a documented self-contradiction in the graded
spec, this sends BOTH: a `multipart/mixed` carrying the exact canonical JSON
bytes as the text body AND the very same bytes as the single named
attachment. Either reader is satisfied, and the two can never disagree
because they are literally the same bytes — the attachment is the file that
was written to disk, never a re-serialization (a pretty-printed re-dump whose
bytes no longer match the artifact is a real, observed near-failure).

SCOPE IS SEND-ONLY, so `drafts` is not available to us: Appendix A grants
`gmail.send` and nothing else, which cannot create a draft. Any safety gate
built on "draft it first" depends on a permission this project does not have,
which is why the gate here is the RECIPIENT itself (see `resolve_recipient`).
"""

from __future__ import annotations

import base64
import logging
from email.message import EmailMessage
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Appendix A §1.3: the minimum necessary, and never a read scope.
GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"

# App. F table 20 [כתובת דיווחי הסוכן] — the JSON reporting address.
LECTURER_REPORT_ADDRESS = "rmisegal+uoh26finalgame@gmail.com"
# Table 20 also lists the lecturer's general address. Both are guarded: a
# practice send must not reach either mailbox.
LECTURER_ADDRESSES = (LECTURER_REPORT_ADDRESS, "rmisegal@gmail.com")

# Where a NON-counted run's mail is addressed. Not a valid address, on purpose:
# PRD-07 requires the lecturer to be structurally unreachable outside a counted
# run rather than merely gated behind a boolean, so that a practice run has
# nowhere to send even if every other check were bypassed.
UNREACHABLE_ADDRESS = "practice-run.invalid"

ATTACHMENT_MIME = ("application", "json")


class NotACountedRunError(Exception):
    """Refused before any credential was touched."""


class MisdirectedReportError(Exception):
    """A counted report aimed somewhere other than the lecturer, or a practice
    send aimed AT the lecturer. Both are refused."""


def _gmail_identity(address: str) -> str:
    """Normalise a Gmail address to the mailbox it actually reaches.

    Gmail ignores dots in the local part and treats everything after `+` as a
    tag, so `R.M.I.Segal+anything@Gmail.com` and `rmisegal@gmail.com` are ONE
    mailbox. A plain string compare against the lecturer's address is therefore
    trivially defeated by a `--to` that is the same inbox spelled differently —
    which would turn the practice flag into a way of mailing the lecturer.
    """
    local, _, domain = address.strip().lower().partition("@")
    if domain == "googlemail.com":
        # Google's own alias domain for the SAME mailbox.
        domain = "gmail.com"
    local = local.partition("+")[0]
    if domain == "gmail.com":
        local = local.replace(".", "")
    return f"{local}@{domain}"


def is_lecturer(address: str) -> bool:
    return _gmail_identity(address) in {_gmail_identity(a) for a in LECTURER_ADDRESSES}


def resolve_recipient(*, counted: bool, override: str | None = None) -> str:
    """`override` (`--to`) makes ANY run a REHEARSAL, counted or not.

    The lecturer's address is produced by exactly one branch: a counted run
    with NO override. That is what a real submission is, and it stays the
    default — omitting `--to` is what you do by accident, not what you type.

    A rehearsal exists because the automatic §9.3 send is otherwise
    untestable: the only trigger is a counted run, and a counted run mails the
    lecturer. `--counted --to X` therefore runs the FULL automatic path —
    same `auto_send`, same Gatekeeper, same ledger interlock — and only
    changes where the mail lands. A separate "test mode" that skipped any of
    that would prove nothing about the path that matters.

    The one absolute rule left: an override may never resolve to the
    lecturer's mailbox, in either mode. A rehearsal arriving at the reporting
    address is a false submission, and it is silent at the moment it happens
    and visible only at grading.
    """
    if override is None:
        return LECTURER_REPORT_ADDRESS if counted else UNREACHABLE_ADDRESS
    if is_lecturer(override):
        raise MisdirectedReportError(
            f"refusing --to {override!r}: that is the lecturer's mailbox, and --to always means a "
            "REHEARSAL. A rehearsal arriving at the reporting address is a false submission. "
            "Use --counted with NO --to when you genuinely mean to submit."
        )
    return override


def build_message(result_path: Path, *, recipient: str, sender: str, game_id: str) -> EmailMessage:
    """A multipart message whose body text and attachment are the SAME bytes —
    the ones already on disk under `result_<game_id>.json`."""
    canonical = result_path.read_bytes()
    message = EmailMessage()
    message["To"] = recipient
    message["From"] = sender
    message["Subject"] = f"[uoh26finalgame] result {game_id}"
    # Body: the canonical bytes, decoded for display only. Appendix A's reading.
    message.set_content(canonical.decode("utf-8"))
    # Attachment: the identical bytes, as the file §9 requires.
    message.add_attachment(
        canonical, maintype=ATTACHMENT_MIME[0], subtype=ATTACHMENT_MIME[1], filename=result_path.name
    )
    return message


def encode(message: EmailMessage) -> dict[str, str]:
    """Gmail's `users.messages.send` body: base64url of the raw RFC-822."""
    return {"raw": base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")}


def send(service: Any, message: EmailMessage) -> dict[str, Any]:
    """One raw send. Wrapped by the Gatekeeper at the call site, never here —
    a transport function that also owns the retry policy hides the 429."""
    return service.users().messages().send(userId="me", body=encode(message)).execute()
