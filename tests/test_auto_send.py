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


# --- friendlies never auto-send -------------------------------------------------


def test_the_peer_command_only_reports_when_the_series_was_counted(monkeypatch):
    """A friendly owes no report to anyone (App. E rule 52), so the automatic
    path must not even be entered."""
    import argparse

    from uoh_mh01 import cli_commands

    called = []
    monkeypatch.setattr(auto_send, "send_counted_series", lambda *a, **k: called.append(1))
    summaries = [{"game_id": "them-vs-us", "sub_game_number": 1}]

    cli_commands._report_counted_series(
        argparse.Namespace(counted=False), CONFIG, object(), summaries, Path(".")
    )
    assert called == []


def test_an_aborted_series_with_no_summaries_reports_nothing(monkeypatch):
    import argparse

    from uoh_mh01 import cli_commands

    called = []
    monkeypatch.setattr(auto_send, "send_counted_series", lambda *a, **k: called.append(1))
    cli_commands._report_counted_series(argparse.Namespace(counted=True), CONFIG, object(), [], Path("."))
    assert called == []


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
