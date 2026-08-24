"""Automatic end-of-series reporting (book §9.3) and its interlocks.

§9.3 requires each agent to mail its own report with no human step, and names
the danger in the same breath — automation is "a blessing and a trap", because
it hands a live mail account to code that may contain a bug. So these tests
care less about the happy path than about everything that must NOT happen: no
second send, no bad report, no friendly reaching the lecturer.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from uoh_mh01.domain.config import load_config
from uoh_mh01.report import auto_send, ledger
from uoh_mh01.report.auto_send import blocking_reasons, send_counted_series
from uoh_mh01.report.result_artifact import missing_mandatory_fields

CONFIG = load_config(Path(__file__).resolve().parents[1] / "config" / "game.json")
COMMIT = "a25eec5684affb400476a2eb1c65962506a40770"


class StubGmail:
    """Records what would have been sent. Never touches the network."""

    def __init__(self, fail: Exception | None = None) -> None:
        self.sends: list[dict] = []
        self.fail = fail

    def users(self):
        return self

    def messages(self):
        return self

    def send(self, userId, body):  # noqa: N803 - Gmail's own parameter name
        outer = self

        class _Exec:
            def execute(self):
                if outer.fail:
                    raise outer.fail
                outer.sends.append(body)
                return {"id": f"stub-{len(outer.sends)}"}

        return _Exec()


def _series(tmp_path: Path, *, commit: str | None = COMMIT, passed: bool = True, n: int = 2) -> str:
    """Write a minimal but real series to disk: one declaration, n sub-game logs."""
    game_id = "them-vs-us"
    (tmp_path / f"declaration_{game_id}.json").write_text(
        json.dumps(
            {
                "game_id": game_id,
                "game_uid": "uid-1234",
                "groups": {
                    "mine": {"group_id": "uoh-mh01", "repos": {"cop": "https://example.invalid/us"}},
                    "opponent": {
                        "group_id": "them",
                        "repos": {"cop": "https://example.invalid/them"},
                        "github_commit": "9c17b5a9",
                        "tokens_total": 0,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    for i in range(1, n + 1):
        (tmp_path / f"log_{game_id}_g{i:02d}.json").write_text(
            json.dumps(
                {
                    "summary": {
                        "sub_game_number": i,
                        "role": "police" if i % 2 else "thief",
                        "result": "survival",
                        "winner_role": "thief",
                        "offending_side": None,
                        "started_at": "2026-08-24T09:00:00+00:00",
                        "ended_at": "2026-08-24T09:04:00+00:00",
                        "audit": {
                            "passed": passed,
                            "verified_steps": 34 if passed else 0,
                            "failed_steps": [] if passed else [3],
                            "reason": None if passed else "mismatch",
                        },
                    },
                    "records": [
                        {
                            "step": 0,
                            "payload": {
                                "step": 0,
                                "type": "system_spec",
                                "spec": {},
                                "code_version": "0.1.0",
                                "group_name": "us",
                                "sub_game_number": i,
                                "github_commit": commit,
                            },
                            "nonce": "n",
                            "commit": "c",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
    return game_id


def _send(tmp_path, service, **kwargs):
    return send_counted_series(
        tmp_path,
        kwargs.pop("game_id", "them-vs-us"),
        CONFIG,
        own_group_id="uoh-mh01",
        ledger_path=tmp_path / "counted_games.json",
        service=service,
        **kwargs,
    )


# --- the happy path -------------------------------------------------------------


def test_a_clean_counted_series_sends_itself_with_no_human_step(tmp_path):
    game_id = _series(tmp_path)
    service = StubGmail()
    outcome = _send(tmp_path, service, game_id=game_id)

    assert outcome.sent, outcome.reason
    assert len(service.sends) == 1
    assert outcome.result_path.name == f"result_{game_id}.json"


def test_a_successful_send_lands_in_the_ledger_as_sent(tmp_path):
    _series(tmp_path)
    _send(tmp_path, StubGmail())
    row = ledger.find("uid-1234", path=tmp_path / "counted_games.json")
    assert row["status"] == ledger.STATUS_SENT
    assert row["opponent_group_id"] == "them"


# --- one send per series, ever --------------------------------------------------


def test_a_second_attempt_on_the_same_series_sends_nothing(tmp_path):
    _series(tmp_path)
    service = StubGmail()
    assert _send(tmp_path, service).sent
    second = _send(tmp_path, service)
    assert not second.sent
    assert "already holds" in second.reason
    assert len(service.sends) == 1, "the lecturer must not receive the same series twice"


def test_a_row_stranded_mid_send_also_blocks_a_retry(tmp_path):
    """A process killed between the two ledger writes leaves `sending`. A
    missed send is recoverable by hand; a duplicate is not recallable, so the
    safe side of that trade is to refuse."""
    _series(tmp_path)
    path = tmp_path / "counted_games.json"
    ledger.record_counted_series(
        opponent_group_id="them",
        game_id="them-vs-us",
        game_uid="uid-1234",
        ended_at="x",
        status=ledger.STATUS_SENDING,
        path=path,
    )
    service = StubGmail()
    outcome = _send(tmp_path, service)
    assert not outcome.sent
    assert service.sends == []


def test_a_failed_send_is_recorded_as_failed_not_sent(tmp_path):
    _series(tmp_path)
    outcome = _send(tmp_path, StubGmail(fail=RuntimeError("network down")))
    assert not outcome.sent
    assert "network down" in outcome.reason
    row = ledger.find("uid-1234", path=tmp_path / "counted_games.json")
    assert row["status"] == ledger.STATUS_FAILED
    assert "network down" in row["detail"]
    assert not ledger.already_reported("uid-1234", path=tmp_path / "counted_games.json")


# --- refuse to send a bad report ------------------------------------------------


def test_a_failed_audit_blocks_the_automatic_send(tmp_path):
    """A bad report sent automatically is worse than one not sent: nobody is
    watching an automatic send to notice."""
    _series(tmp_path, passed=False)
    service = StubGmail()
    outcome = _send(tmp_path, service)
    assert not outcome.sent
    assert any("audit did not confirm" in b for b in outcome.blockers)
    assert service.sends == []


def test_a_missing_commit_blocks_the_automatic_send(tmp_path):
    _series(tmp_path, commit=None)
    service = StubGmail()
    outcome = _send(tmp_path, service)
    assert not outcome.sent
    assert any("github_commit" in b for b in outcome.blockers)
    assert service.sends == []


def test_a_blocked_series_leaves_no_ledger_row_at_all(tmp_path):
    """It never got as far as attempting, so it must not look attempted."""
    _series(tmp_path, passed=False)
    _send(tmp_path, StubGmail())
    assert ledger.find("uid-1234", path=tmp_path / "counted_games.json") is None


def test_the_artifact_is_still_written_when_the_send_is_blocked(tmp_path):
    """The games were played; their report belongs on disk regardless."""
    _series(tmp_path, passed=False)
    outcome = _send(tmp_path, StubGmail())
    assert outcome.result_path.is_file()


# --- the mandatory-field rules --------------------------------------------------


def test_missing_mandatory_fields_names_each_gap():
    result = {
        "links": {},
        "sub_games": [{"sub_game_number": 1, "github_commit": {"us": None, "them": "abc"}}],
        "final_result": {"tokens_total_series": {"us": None, "them": None}},
    }
    gaps = missing_mandatory_fields(result)
    assert any("links.github" in g for g in gaps)
    assert any("github_commit" in g and "sub-game 1" in g for g in gaps)
    assert any("tokens_total_series" in g for g in gaps)


def test_a_complete_report_has_no_gaps(tmp_path):
    _series(tmp_path)
    from uoh_mh01.report import pipeline

    result = pipeline.build(tmp_path, "them-vs-us", CONFIG, ledger_path=tmp_path / "counted_games.json")
    assert missing_mandatory_fields(result) == []
    assert blocking_reasons(result, ledger_path=tmp_path / "counted_games.json") == []


# --- a friendly sends nothing unless it is told where ---------------------------


def test_a_friendly_with_no_to_sends_nothing_at_all(monkeypatch):
    """A warm-up owes no report to anyone (App. E rule 52), so the automatic
    path must not even be entered."""
    import argparse

    from uoh_mh01 import cli_commands

    called = []
    monkeypatch.setattr(auto_send, "send_counted_series", lambda *a, **k: called.append(1))
    summaries = [{"game_id": "them-vs-us", "sub_game_number": 1}]

    ok = cli_commands._send_series_report(
        argparse.Namespace(counted=False, to=None), CONFIG, object(), summaries, Path(".")
    )
    assert called == []
    assert ok is True


def test_an_aborted_counted_series_is_a_loud_failure(monkeypatch, capsys):
    """No sub-games means nothing to build a report from. For a COUNTED series
    that is a lost game, so it must be loud and it must not report success."""
    import argparse

    from uoh_mh01 import cli_commands

    called = []
    monkeypatch.setattr(auto_send, "send_counted_series", lambda *a, **k: called.append(1))
    ok = cli_commands._send_series_report(
        argparse.Namespace(counted=True, to=None), CONFIG, object(), [], Path(".")
    )
    assert called == []
    assert ok is False
    assert "WAS NOT REPORTED" in capsys.readouterr().err


def test_every_summary_carries_the_game_id_the_send_needs():
    """The peer process must know which series it just played without
    re-reading the declaration off disk."""
    import inspect

    from uoh_mh01.infra import series_subgame

    source = inspect.getsource(series_subgame.play_one_sub_game)
    assert '"game_id": game_id' in source
    assert '"game_uid": game_uid' in source


# --- the send still goes through the Gatekeeper ---------------------------------


def test_the_send_is_gatekeeper_wrapped(tmp_path, monkeypatch):
    """§9.3.1 pairs the automation requirement with the Gatekeeper. If a future
    change sends directly, this fails."""
    from uoh_mh01.report import pipeline

    executed = []
    real = pipeline.Gatekeeper

    class Spy(real):
        def execute(self, call, *args, **kwargs):
            executed.append(self.service)
            return super().execute(call, *args, **kwargs)

    monkeypatch.setattr(pipeline, "Gatekeeper", Spy)
    _series(tmp_path)
    assert _send(tmp_path, StubGmail()).sent
    assert executed == ["gmail"]


def test_the_lecturer_address_is_the_fixed_destination(tmp_path):
    """Book §9.3: "זוהי הכתובת היחידה והמחייבת" - the single mandatory address,
    fixed in each agent's sending code."""
    from uoh_mh01.infra.gmail_sender import LECTURER_REPORT_ADDRESS

    _series(tmp_path)
    service = StubGmail()
    _send(tmp_path, service)
    import base64
    from email import message_from_bytes

    raw = base64.urlsafe_b64decode(service.sends[0]["raw"])
    assert message_from_bytes(raw)["To"] == LECTURER_REPORT_ADDRESS


# --- a friendly is the same path with a different mailbox -----------------------


def _friendly(tmp_path, service, to="me@example.com"):
    return send_counted_series(
        tmp_path,
        "them-vs-us",
        CONFIG,
        own_group_id="uoh-mh01",
        counted=False,
        ledger_path=tmp_path / "counted_games.json",
        to=to,
        service=service,
    )


def test_a_friendly_delivers_to_the_named_address(tmp_path):
    import base64
    from email import message_from_bytes

    from uoh_mh01.infra.gmail_sender import LECTURER_REPORT_ADDRESS

    _series(tmp_path)
    service = StubGmail()
    outcome = _friendly(tmp_path, service)

    assert outcome.sent, outcome.reason
    assert outcome.counted is False
    raw = base64.urlsafe_b64decode(service.sends[0]["raw"])
    recipient = message_from_bytes(raw)["To"]
    assert recipient == "me@example.com"
    assert recipient != LECTURER_REPORT_ADDRESS


def test_a_friendly_never_writes_the_committed_league_ledger(tmp_path):
    """`league/` is committed evidence of COUNTED play. A warm-up row there
    would make the next real series against that opponent declare
    `first_meeting_between_groups` wrongly - a rules-37/38 false declaration
    that App. E rule 35 charges to the innocent opponent too."""
    _series(tmp_path)
    real_ledger = tmp_path / "counted_games.json"
    assert _friendly(tmp_path, StubGmail()).sent
    assert not real_ledger.exists()


def test_a_friendly_does_not_block_the_counted_send_that_follows(tmp_path):
    """Practise, then really submit."""
    _series(tmp_path)
    service = StubGmail()
    assert _friendly(tmp_path, service).sent

    real = _send(tmp_path, service, counted=True)
    assert real.sent, real.reason
    assert real.counted is True
    assert ledger.already_reported("uid-1234", path=tmp_path / "counted_games.json")
    assert len(service.sends) == 2


def test_a_friendly_may_be_sent_more_than_once(tmp_path):
    """The interlock is about counted evidence, not about mail. Re-sending a
    practice report is a legitimate thing to want, and a runaway loop is the
    Gatekeeper's job, which a friendly shares."""
    _series(tmp_path)
    service = StubGmail()
    assert _friendly(tmp_path, service).sent
    assert _friendly(tmp_path, service).sent
    assert len(service.sends) == 2


def test_a_friendly_reports_the_same_numbers_a_counted_run_would(tmp_path):
    """It reads the REAL ledger for report CONTENT, so first_meeting and the
    game count are not quietly different - otherwise it rehearses nothing."""
    _series(tmp_path)
    real_ledger = tmp_path / "counted_games.json"
    ledger.record_counted_series(
        opponent_group_id="them", game_id="older", game_uid="uid-older", ended_at="x", path=real_ledger
    )
    outcome = _friendly(tmp_path, StubGmail())
    final = json.loads(outcome.result_path.read_text(encoding="utf-8"))["final_result"]
    # A prior counted series against `them` exists, so this is NOT a first
    # meeting and our own count is 2 - exactly what a counted run would say.
    assert final["first_meeting_between_groups"] is False
    assert final["games_played_including_this"]["uoh-mh01"] == 2


def test_a_friendly_still_refuses_a_bad_report(tmp_path):
    """Same refusal rules either way: a friendly that happily mailed a report
    the counted path would reject would prove nothing about the counted path."""
    _series(tmp_path, passed=False)
    service = StubGmail()
    outcome = _friendly(tmp_path, service)
    assert not outcome.sent
    assert service.sends == []


def test_a_friendly_is_still_gatekeeper_wrapped(tmp_path, monkeypatch):
    from uoh_mh01.report import pipeline

    executed = []
    real = pipeline.Gatekeeper

    class Spy(real):
        def execute(self, call, *args, **kwargs):
            executed.append(self.service)
            return super().execute(call, *args, **kwargs)

    monkeypatch.setattr(pipeline, "Gatekeeper", Spy)
    _series(tmp_path)
    assert _friendly(tmp_path, StubGmail()).sent
    assert executed == ["gmail"]


def test_a_failed_send_can_be_retried_but_a_sent_one_cannot(tmp_path):
    """The manual fallback exists precisely for a failed automatic send, so a
    `failed` row must not lock it out. `sent` and `sending` still do."""
    _series(tmp_path)
    path = tmp_path / "counted_games.json"
    down = StubGmail(fail=RuntimeError("network down"))
    assert not _send(tmp_path, down).sent
    assert ledger.find("uid-1234", path=path)["status"] == ledger.STATUS_FAILED

    up = StubGmail()
    retry = _send(tmp_path, up)
    assert retry.sent, retry.reason
    assert len(up.sends) == 1

    # ...and now it is closed for good.
    assert not _send(tmp_path, up).sent
    assert len(up.sends) == 1


# --- a DECLARED CORRECTION: the one sanctioned second send ----------------------


def _correct(tmp_path, service, reason="the first send was an accident on a friendly", **kwargs):
    return _send(tmp_path, service, correction=reason, **kwargs)


def _sent_once(tmp_path):
    """Get a series into the state this feature exists for: already reported."""
    _series(tmp_path)
    first = _send(tmp_path, StubGmail())
    assert first.sent
    return tmp_path / "counted_games.json"


def test_without_a_correction_a_reported_series_stays_closed(tmp_path):
    """The baseline the correction must not erode."""
    path = _sent_once(tmp_path)
    service = StubGmail()
    assert not _send(tmp_path, service).sent
    assert service.sends == []
    assert len(ledger.attempts("uid-1234", path=path)) == 1


def test_a_declared_correction_sends_where_a_plain_resend_would_not(tmp_path):
    _sent_once(tmp_path)
    service = StubGmail()
    outcome = _correct(tmp_path, service)
    assert outcome.sent, outcome.reason
    assert outcome.attempt == 2
    assert len(service.sends) == 1


def test_a_correction_appends_and_never_edits_the_row_it_supersedes(tmp_path):
    """The ledger is the evidence that a report was sent. Evidence that can be
    rewritten when it becomes inconvenient is not evidence."""
    path = _sent_once(tmp_path)
    before = json.loads(path.read_text(encoding="utf-8"))["counted_series"][0]

    assert _correct(tmp_path, StubGmail(), reason="wrong tie rule").sent

    rows = ledger.attempts("uid-1234", path=path)
    assert len(rows) == 2
    assert rows[0] == before, "the superseded row must be byte-for-byte untouched"
    assert rows[1]["status"] == ledger.STATUS_SENT
    assert rows[1]["correction_of"] == 1
    assert rows[1]["correction_reason"] == "wrong tie rule"


def test_a_correction_does_not_inflate_the_game_count_declaration(tmp_path):
    """Two rows, one series. Counting rows would overstate how many counted
    games this group has played - a false declaration under ch.9.2.1."""
    path = _sent_once(tmp_path)
    assert ledger.counted_games_played(path=path) == 1
    assert _correct(tmp_path, StubGmail()).sent
    assert ledger.counted_games_played(path=path) == 1


def test_the_latest_attempt_is_what_the_interlock_reads(tmp_path):
    path = _sent_once(tmp_path)
    assert _correct(tmp_path, StubGmail()).sent
    assert ledger.attempt_of(ledger.find("uid-1234", path=path)) == 2
    # ...and that correction is itself now closed to a plain resend.
    service = StubGmail()
    assert not _send(tmp_path, service).sent
    assert service.sends == []


def test_a_correction_needs_something_to_correct(tmp_path):
    """THE property that keeps the interlock intact: with no delivered report
    on record, the flag refuses rather than waving a first send through."""
    _series(tmp_path)
    service = StubGmail()
    outcome = _correct(tmp_path, service)
    assert not outcome.sent
    assert service.sends == []
    assert any("no earlier send" in b for b in outcome.blockers)


def test_a_send_of_unknown_fate_is_not_correctable(tmp_path):
    """A `sending` row may or may not have reached the lecturer. Correcting it
    would be guessing, and guessing wrong means two reports for one series."""
    _series(tmp_path)
    path = tmp_path / "counted_games.json"
    ledger.record_counted_series(
        opponent_group_id="them", game_id="them-vs-us", game_uid="uid-1234", ended_at="x",
        status=ledger.STATUS_SENDING, path=path,
    )
    outcome = _correct(tmp_path, StubGmail())
    assert not outcome.sent
    assert any("no delivered report to supersede" in b for b in outcome.blockers)


def test_a_correction_must_state_a_reason(tmp_path):
    _sent_once(tmp_path)
    outcome = _correct(tmp_path, StubGmail(), reason="   ")
    assert not outcome.sent
    assert any("must state its reason" in b for b in outcome.blockers)


def test_a_friendly_cannot_be_a_correction(tmp_path):
    _sent_once(tmp_path)
    outcome = _send(tmp_path, StubGmail(), counted=False, to="me@example.com", correction="whatever")
    assert not outcome.sent
    assert any("--counted" in b for b in outcome.blockers)


def test_a_correction_still_refuses_an_unfit_report(tmp_path):
    """It skips the duplicate-send blocker and nothing else. A correction that
    is itself wrong is not a correction."""
    _series(tmp_path, passed=False)
    path = tmp_path / "counted_games.json"
    ledger.record_counted_series(
        opponent_group_id="them", game_id="them-vs-us", game_uid="uid-1234", ended_at="x",
        status=ledger.STATUS_SENT, path=path,
    )
    service = StubGmail()
    outcome = _correct(tmp_path, service)
    assert not outcome.sent
    assert service.sends == []
    assert any("audit" in b for b in outcome.blockers)


def test_a_correction_is_still_gatekeeper_wrapped(tmp_path, monkeypatch):
    from uoh_mh01.report import pipeline

    executed = []
    real = pipeline.Gatekeeper

    class Spy(real):
        def execute(self, call, *args, **kwargs):
            executed.append(self.service)
            return super().execute(call, *args, **kwargs)

    _sent_once(tmp_path)
    monkeypatch.setattr(pipeline, "Gatekeeper", Spy)
    assert _correct(tmp_path, StubGmail()).sent
    assert executed == ["gmail"]


def test_a_correction_still_goes_to_the_lecturer(tmp_path):
    import base64
    from email import message_from_bytes

    from uoh_mh01.infra.gmail_sender import LECTURER_REPORT_ADDRESS

    _sent_once(tmp_path)
    service = StubGmail()
    assert _correct(tmp_path, service).sent
    raw = base64.urlsafe_b64decode(service.sends[0]["raw"])
    assert message_from_bytes(raw)["To"] == LECTURER_REPORT_ADDRESS


def test_a_row_written_before_corrections_existed_counts_as_attempt_one(tmp_path):
    """The real ledger's ali-ahm1 row has no `attempt` key. It must still be
    superseded correctly rather than treated as a different series."""
    _series(tmp_path)
    path = tmp_path / "counted_games.json"
    path.write_text(
        json.dumps({
            "schema_version": "1.0",
            "counted_series": [{
                "opponent_group_id": "them", "game_id": "them-vs-us", "game_uid": "uid-1234",
                "ended_at": "2026-08-23T21:23:31+00:00", "status": "sent",
                "detail": "gmail message id 1a03085ccd9e11fa",
            }],
        }),
        encoding="utf-8",
    )
    outcome = _correct(tmp_path, StubGmail())
    assert outcome.sent, outcome.reason
    rows = ledger.attempts("uid-1234", path=path)
    assert ledger.attempt_of(rows[0]) == 1
    assert rows[1]["correction_of"] == 1


# --- the CLI surface a correction is reachable through --------------------------


def test_correction_without_counted_is_refused_by_the_cli(monkeypatch, capsys):
    from uoh_mh01.__main__ import main

    called = []
    monkeypatch.setattr(auto_send, "send_counted_series", lambda *a, **k: called.append(k))
    code = main(["report", "--game-id", "g", "--correction", "because"])
    assert code == 2
    assert called == []
    assert "--counted" in capsys.readouterr().err


def test_the_peer_command_cannot_declare_a_correction():
    """A correction is a human deciding an already-delivered report was wrong.
    The automatic sender must never be able to authorize one for itself, so the
    flag does not exist on `peer` at all."""
    from uoh_mh01.__main__ import main

    with pytest.raises(SystemExit) as exc:
        main(["peer", "--role", "police", "--counted", "--correction", "because"])
    assert exc.value.code == 2


def _cli_report(monkeypatch, tmp_path, argv, outcome=None):
    """Drive `main(["report", ...])` with only the send stubbed."""
    from uoh_mh01.__main__ import main

    _series(tmp_path)
    calls = []
    result = outcome or auto_send.AutoSendOutcome(sent=True, message_id="stub-1", attempt=1)
    monkeypatch.setattr(auto_send, "send_counted_series", lambda *a, **k: calls.append(k) or result)
    code = main(["report", "--game-id", "them-vs-us", "--log-dir", str(tmp_path), *argv])
    return code, calls


def test_the_cli_threads_the_correction_reason_to_the_sender(monkeypatch, tmp_path, capsys):
    sent = auto_send.AutoSendOutcome(sent=True, message_id="stub-1", attempt=2)
    code, calls = _cli_report(
        monkeypatch, tmp_path, ["--counted", "--correction", "accidental send on a friendly"], outcome=sent
    )
    assert code == 0
    assert calls and calls[0]["correction"] == "accidental send on a friendly"
    assert calls[0]["counted"] is True

    captured = capsys.readouterr()
    assert "DECLARED CORRECTION" in captured.err
    assert "accidental send on a friendly" in captured.err
    # The operator must be able to see it landed as a supersession, not a first send.
    assert "attempt 2" in captured.out


def test_an_ordinary_counted_report_carries_no_correction_and_warns_it_is_manual(monkeypatch, tmp_path, capsys):
    code, calls = _cli_report(monkeypatch, tmp_path, ["--counted"])
    assert code == 0
    assert calls[0]["correction"] is None
    captured = capsys.readouterr()
    assert "MANUAL FALLBACK" in captured.err
    assert "DECLARED CORRECTION" not in captured.err


def test_a_refused_correction_exits_nonzero_and_lists_why(monkeypatch, tmp_path, capsys):
    refused = auto_send.AutoSendOutcome(
        sent=False, reason="this is not a valid declared correction",
        blockers=["there is no earlier send for this series to correct"],
    )
    code, _ = _cli_report(monkeypatch, tmp_path, ["--counted", "--correction", "nope"], outcome=refused)
    assert code == 3
    err = capsys.readouterr().err
    assert "NOT SENT" in err
    assert "no earlier send" in err
