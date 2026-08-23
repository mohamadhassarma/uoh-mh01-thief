"""The report email: attachment, byte-identity, scope, and the recipient gate.

Book §9: the report MUST be an attached JSON file and a free-text body is
REJECTED, at the cost of the round's league points. Appendix A's own listing
then builds a plain `MIMEText` body with no attachment. These tests pin the
resolution — send BOTH, from the same bytes — so neither reading can fail us
and the two halves can never drift apart.
"""

from __future__ import annotations

import base64
import json
from email import message_from_bytes
from pathlib import Path

import pytest

from uoh_mh01.infra.gmail_sender import (
    GMAIL_SEND_SCOPE,
    LECTURER_REPORT_ADDRESS,
    UNREACHABLE_ADDRESS,
    build_message,
    encode,
    resolve_recipient,
)


@pytest.fixture
def result_file(tmp_path) -> Path:
    path = tmp_path / "result_them-vs-us.json"
    path.write_text(json.dumps({"game_id": "them-vs-us", "hebrew": "תוצאה"}, ensure_ascii=False), encoding="utf-8")
    return path


def _parts(message):
    return list(message.walk())


def test_the_report_is_attached_as_a_named_json_file(result_file):
    message = build_message(result_file, recipient="x@example.invalid", sender="me", game_id="them-vs-us")
    attachments = [p for p in _parts(message) if p.get_filename()]
    assert len(attachments) == 1
    assert attachments[0].get_filename() == "result_them-vs-us.json"
    assert attachments[0].get_content_type() == "application/json"


def test_the_attachment_bytes_are_the_file_on_disk_not_a_reserialization(result_file):
    """A pretty-printed re-dump whose bytes no longer match the artifact is a
    real, observed near-failure — the lecturer's copy must be the repo's copy."""
    message = build_message(result_file, recipient="x@example.invalid", sender="me", game_id="them-vs-us")
    attachment = next(p for p in _parts(message) if p.get_filename())
    assert attachment.get_payload(decode=True) == result_file.read_bytes()


def test_the_body_carries_the_same_bytes_as_the_attachment(result_file):
    """Appendix A's reading and §9's reading, satisfied from ONE source."""
    message = build_message(result_file, recipient="x@example.invalid", sender="me", game_id="them-vs-us")
    body = next(p for p in _parts(message) if p.get_content_type() == "text/plain" and not p.get_filename())
    assert body.get_payload(decode=True).decode("utf-8").rstrip("\n") == result_file.read_text(encoding="utf-8")


def test_non_ascii_survives_the_round_trip(result_file):
    """The report is Hebrew-bearing; a latin-1 body would corrupt it silently."""
    message = build_message(result_file, recipient="x@example.invalid", sender="me", game_id="them-vs-us")
    raw = base64.urlsafe_b64decode(encode(message)["raw"])
    attachment = next(p for p in message_from_bytes(raw).walk() if p.get_filename())
    assert json.loads(attachment.get_payload(decode=True).decode("utf-8"))["hebrew"] == "תוצאה"


def test_the_gmail_body_is_base64url_of_the_raw_message(result_file):
    message = build_message(result_file, recipient="x@example.invalid", sender="me", game_id="them-vs-us")
    encoded = encode(message)
    assert set(encoded) == {"raw"}
    assert base64.urlsafe_b64decode(encoded["raw"]) == message.as_bytes()


# --- the gates ------------------------------------------------------------------


def test_a_counted_run_resolves_to_the_lecturers_reporting_address():
    assert resolve_recipient(counted=True) == LECTURER_REPORT_ADDRESS


def test_a_warmup_resolves_to_an_address_that_cannot_be_delivered():
    """PRD-07: structurally unreachable, not merely gated behind a boolean —
    a practice run must have nowhere to send even if every check were bypassed."""
    recipient = resolve_recipient(counted=False)
    assert recipient == UNREACHABLE_ADDRESS
    assert "@" not in recipient
    assert LECTURER_REPORT_ADDRESS not in recipient


def test_the_only_granted_scope_is_send_only():
    """Appendix A §1.3: the minimum necessary, and never a read scope."""
    from uoh_mh01.infra import gmail_auth

    assert gmail_auth.SCOPES == [GMAIL_SEND_SCOPE]
    assert GMAIL_SEND_SCOPE.endswith("/gmail.send")
    assert not any("readonly" in s or "modify" in s for s in gmail_auth.SCOPES)


def test_the_secrets_live_outside_the_repo():
    from uoh_mh01.infra import gmail_auth

    repo = Path(__file__).resolve().parents[1]
    for path in (gmail_auth.credentials_path(), gmail_auth.token_path()):
        assert repo not in path.parents, f"{path} is inside the repo"


def test_both_secret_filenames_are_gitignored_anyway():
    """Belt and braces: they live outside the tree, and the ignore rules mean
    a stray copy inside it still cannot be committed."""
    ignored = (Path(__file__).resolve().parents[1] / ".gitignore").read_text(encoding="utf-8")
    assert "credentials.json" in ignored
    assert "token.json" in ignored


def test_loading_credentials_never_opens_a_browser(tmp_path):
    """A send that could pop a consent screen mid-run can hang forever on a
    headless box; authorization is a separate, human-invoked command."""
    from uoh_mh01.infra.gmail_auth import NotAuthorizedError, load_credentials

    with pytest.raises(NotAuthorizedError, match="authorize-gmail"):
        load_credentials(tmp_path)


# --- the --to override ----------------------------------------------------------


def test_to_sends_to_the_named_address_on_a_practice_run():
    assert resolve_recipient(counted=False, override="me@example.com") == "me@example.com"


def test_counted_with_to_is_a_rehearsal_not_a_submission():
    """`--to` makes ANY run a rehearsal. This is the only way to exercise the
    automatic §9.3 send at all: its sole trigger is a counted run, and a
    counted run mails the lecturer."""
    assert resolve_recipient(counted=True, override="me@example.com") == "me@example.com"


def test_counted_without_to_still_reaches_the_lecturer():
    assert resolve_recipient(counted=True, override=None) == LECTURER_REPORT_ADDRESS


@pytest.mark.parametrize(
    "spelling",
    [
        "rmisegal+uoh26finalgame@gmail.com",
        "rmisegal@gmail.com",
        "RMISEGAL@GMAIL.COM",
        "r.m.i.segal@gmail.com",
        "R.M.I.Segal+practice@Gmail.com",
        "rmisegal@googlemail.com",
        "  rmisegal+x@gmail.com  ",
    ],
)
@pytest.mark.parametrize("counted", [True, False])
def test_to_cannot_be_used_as_a_back_door_to_the_lecturer(spelling, counted):
    """Gmail ignores dots and everything after `+`, so a plain string compare
    would let `--to` reach the very mailbox the practice gate exists to
    protect — turning the safety flag into the bypass."""
    from uoh_mh01.infra.gmail_sender import MisdirectedReportError

    with pytest.raises(MisdirectedReportError, match="lecturer's mailbox"):
        resolve_recipient(counted=counted, override=spelling)


def test_an_ordinary_address_that_merely_resembles_the_lecturer_is_allowed():
    """The guard must not be so broad it blocks real addresses."""
    for address in ("rmisegal@example.com", "notrmisegal@gmail.com", "rmisegal2@gmail.com"):
        assert resolve_recipient(counted=False, override=address) == address
        assert resolve_recipient(counted=True, override=address) == address


def test_only_a_counted_run_with_no_override_reaches_the_lecturer():
    """The whole safety property in one assertion: exactly one input
    combination produces the reporting address."""
    combinations = {
        (True, None): LECTURER_REPORT_ADDRESS,
        (False, None): UNREACHABLE_ADDRESS,
        (True, "me@example.com"): "me@example.com",
        (False, "me@example.com"): "me@example.com",
    }
    for (counted, override), expected in combinations.items():
        assert resolve_recipient(counted=counted, override=override) == expected
