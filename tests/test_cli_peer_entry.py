"""The `peer` command's automatic report, driven through the REAL entry point.

THIS FILE EXISTS BECAUSE OF A SILENT BUG. `cmd_peer` played a full counted
series and returned 0 having sent nothing: no mail, no banner, no blocker, no
reason. The send helper was defined, tested, and never called. Every existing
test called that helper directly, so the suite was green while the one thing
book section 9.3 requires - the agent mailing its own report with no human step
- did not happen at all.

So these tests go in through `main(["peer", ...])`, argparse included, and stub
only at the network edges (`run_series`, and the send itself). A test that
calls the helper cannot tell whether anything calls the helper.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from uoh_mh01 import cli_commands
from uoh_mh01.__main__ import main
from uoh_mh01.report import auto_send

# Both repos ship only their OWN side's peer config, so the role is read off
# the tree rather than hardcoded - this file is mirrored byte-for-byte.
REPO_ROOT = Path(__file__).resolve().parents[1]
OWN_ROLE = "police" if (REPO_ROOT / "config" / "police").is_dir() else "thief"

SUMMARIES = [
    {
        "sub_game_number": 1,
        "game_id": "them-vs-us",
        "role": OWN_ROLE,
        "terminal_condition": "thief_survived",
        "police_score": 0,
        "thief_score": 15,
        "audit_of_opponent_by_me": True,
    }
]


@pytest.fixture
def peer_run(monkeypatch, tmp_path):
    """Drive `main(["peer", ...])` with the network replaced and record what
    the automatic send was asked to do."""
    sent: list[dict] = []
    series_kwargs: list[dict] = []

    def _run(outcome=None, raises=None, summaries=SUMMARIES, argv=()):
        async def fake_run_series(role, config, peer_config, **kwargs):
            series_kwargs.append(kwargs)
            return summaries

        def fake_send(*args, **kwargs):
            sent.append(kwargs)
            if raises is not None:
                raise raises
            return outcome if outcome is not None else auto_send.AutoSendOutcome(
                sent=True, message_id="stub-1", counted=kwargs["counted"], recipient=kwargs["to"]
            )

        from uoh_mh01.infra import series

        monkeypatch.setattr(series, "run_series", fake_run_series)
        monkeypatch.setattr(auto_send, "send_counted_series", fake_send)
        code = main(["peer", "--role", OWN_ROLE, "--log-dir", str(tmp_path), *argv])
        return code, sent, series_kwargs

    return _run


def test_a_counted_series_sends_its_report_without_a_human_step(peer_run):
    """The regression. Book section 9.3: at the end of a counted series the
    agent mails its own report - no separate command, no human."""
    code, sent, _ = peer_run(argv=["--counted"])

    assert sent, "the counted series finished and never entered the automatic send path"
    assert sent[0]["counted"] is True
    assert sent[0]["to"] is None
    assert code == 0


def test_the_counted_flag_also_reaches_the_series_runner(peer_run):
    """It always did - the dirty-tree gate worked - which is exactly why the
    missing send was so easy to miss."""
    _, _, series_kwargs = peer_run(argv=["--counted"])
    assert series_kwargs[0]["counted"] is True


def test_a_friendly_with_to_sends_through_the_same_path(peer_run):
    code, sent, _ = peer_run(argv=["--to", "me@example.com"])

    assert sent, "a friendly with --to must send"
    assert sent[0]["to"] == "me@example.com"
    assert sent[0]["counted"] is False
    assert code == 0


def test_a_friendly_with_no_to_sends_nothing_and_still_succeeds(peer_run):
    code, sent, _ = peer_run()
    assert sent == []
    assert code == 0


def test_a_counted_series_that_does_not_send_exits_nonzero_and_says_why(peer_run, capsys):
    """A counted series that ends without either a send or a stated reason is
    the one outcome that must never be quiet: the game is played, it cannot be
    replayed, and it is worth nothing unreported."""
    refused = auto_send.AutoSendOutcome(
        sent=False, reason="the report is not fit to send", blockers=["github_commit missing for sub-game 1"]
    )
    code, sent, _ = peer_run(outcome=refused, argv=["--counted"])

    assert sent, "it must at least have tried"
    assert code != 0
    err = capsys.readouterr().err
    assert "COUNTED SERIES WAS NOT REPORTED" in err
    assert "not fit to send" in err
    assert "github_commit missing for sub-game 1" in err


def test_a_send_that_raises_is_loud_but_still_prints_the_series(peer_run, capsys):
    """The games really happened and their artifacts are on disk. Losing the
    printed summary to a traceback would be a second failure on top of the
    first."""
    code, _, _ = peer_run(raises=RuntimeError("token expired"), argv=["--counted"])

    captured = capsys.readouterr()
    assert code != 0
    assert "Sub-game 1" in captured.out
    assert "RuntimeError" in captured.err
    assert "token expired" in captured.err


def test_a_friendly_that_fails_to_send_is_reported_but_not_fatal(peer_run, capsys):
    """Nothing was owed to anyone, so a failed practice send is not a lost
    game and must not look like one."""
    refused = auto_send.AutoSendOutcome(sent=False, reason="stub refused")
    code, _, _ = peer_run(outcome=refused, argv=["--to", "me@example.com"])

    assert code == 0
    err = capsys.readouterr().err
    assert "NOT SENT" in err
    assert "COUNTED SERIES WAS NOT REPORTED" not in err


@pytest.mark.parametrize("command", ["peer", "report"])
def test_counted_and_to_together_are_refused_before_anything_runs(command):
    """Refused by argparse, so a counted series cannot be played to completion
    and only then discover its recipient was never valid."""
    argv = [command, "--role", OWN_ROLE] if command == "peer" else [command, "--game-id", "g"]
    with pytest.raises(SystemExit) as exc:
        main([*argv, "--counted", "--to", "me@example.com"])
    assert exc.value.code == 2


def test_the_peer_command_calls_the_send_helper_at_all():
    """A structural backstop for the exact bug: the helper was defined and
    never referenced, so it could be deleted with the suite still green."""
    import inspect

    assert "_send_series_report(" in inspect.getsource(cli_commands.cmd_peer)
