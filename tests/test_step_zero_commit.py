"""The played commit in the step-0 declaration (book ch.5), the dirty-tree
gate, and the fact that changing the sealed shape breaks nothing.

Our last real series declared `null` for all six sub-games while the opponent
declared theirs — invisible from inside, because a step-0 record is
disclosure-only and nothing we do reads its fields.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from uoh_mh01.domain.crypto import seal, verify
from uoh_mh01.domain.sealed_payload import build_step_zero_payload
from uoh_mh01.domain.state import Side
from uoh_mh01.infra.audit import ReceivedCommitLog, verify_revealed
from uoh_mh01.orchestrator import PeerRuntime
from uoh_mh01.report.series_reader import _own_github_commit, sub_game_rows
from uoh_mh01.shared.build_commit import (
    DirtyWorkingTreeError,
    RepoState,
    assert_declarable,
    current_commit_hash,
    repo_state,
)
from uoh_mh01.shared.peer_config import PeerConfig

COMMIT = "ef1969a2f242d3f54ea6889c9a661c10dcbd1055"


def _peer_config() -> PeerConfig:
    return PeerConfig(
        role="police",
        group_id="uoh-mh01",
        group_name="Hassarma-Agents",
        my_port=8801,
        opponent_url="http://127.0.0.1:8802/mcp",
        turn_timeout_seconds=30,
    )


# --- the record itself ----------------------------------------------------------


def test_the_step_zero_record_declares_the_commit_that_played(config_factory):
    runtime = PeerRuntime(Side.POLICE, config_factory(), _peer_config(), repo_commit=COMMIT)
    record = runtime.seal_step_zero()
    assert record["payload"]["github_commit"] == COMMIT
    assert verify(record["payload"], record["nonce"], record["commit"])


def test_the_commit_is_captured_once_not_re_read_per_sub_game(config_factory):
    """A series is one submission. Sub-games declaring different commits would
    mean the examiner cannot reproduce 'the version that competed'."""
    config = config_factory()
    records = [
        PeerRuntime(Side.POLICE, config, _peer_config(), sub_game_number=n, repo_commit=COMMIT).seal_step_zero()
        for n in (1, 2, 3)
    ]
    assert {r["payload"]["github_commit"] for r in records} == {COMMIT}


def test_the_key_is_always_present_even_when_the_commit_is_unknown(config_factory):
    """Null, not absent, and never the string "unknown" — a downstream check
    cannot tell "unknown" from a real value, so the gap would stop being
    reported while still being a gap."""
    payload = PeerRuntime(Side.POLICE, config_factory(), _peer_config()).seal_step_zero()["payload"]
    assert "github_commit" in payload
    assert payload["github_commit"] is None


# --- shape change safety (emit strictly, receive tolerantly) --------------------


def test_a_peer_that_omits_the_field_still_verifies_on_our_side():
    """Step 0 is disclosure-only: we re-hash whatever payload arrives, verbatim.
    A conformant peer built to the reference (whose step-0 has no
    `github_commit` at all) must not fail our audit for lacking it."""
    reference_shaped = {
        "step": 0,
        "type": "system_spec",
        "sub_game_number": 1,
        "group_name": "them",
        "model": "template",
        "code_version": "3.0.0",
        "spec": {"os": "any"},
    }
    sealed = seal(reference_shaped)
    played = {"step": 1, "role": "thief", "action_type": "move", "detail": "N"}
    played_sealed = seal(played)
    log = ReceivedCommitLog()
    log.record(1, played_sealed["commit"])

    result = verify_revealed(
        [
            {"payload": reference_shaped, "nonce": sealed["nonce"], "commit": sealed["commit"]},
            {"payload": played, "nonce": played_sealed["nonce"], "commit": played_sealed["commit"]},
        ],
        log,
    )
    assert result.passed, result.reason
    assert result.verified_steps == 1  # step 0 is not a played step


def test_our_richer_step_zero_verifies_the_same_way():
    """The added field must not make OUR reveal unverifiable to a peer using
    the reference's serializer — the payload is re-hashed as given."""
    payload = build_step_zero_payload(
        spec={"os": "Windows"}, code_version="0.1.0", group_name="us", sub_game_number=1, github_commit=COMMIT
    )
    sealed = seal(payload)
    result = verify_revealed(
        [{"payload": payload, "nonce": sealed["nonce"], "commit": sealed["commit"]}], ReceivedCommitLog()
    )
    assert result.failed_steps == ()


def test_a_tampered_step_zero_commit_is_still_caught():
    """The whole point of sealing it: changing the declared commit after the
    fact must break the hash."""
    payload = build_step_zero_payload(
        spec={}, code_version="0.1.0", group_name="us", sub_game_number=1, github_commit=COMMIT
    )
    sealed = seal(payload)
    forged = {**payload, "github_commit": "0" * 40}
    result = verify_revealed(
        [{"payload": forged, "nonce": sealed["nonce"], "commit": sealed["commit"]}], ReceivedCommitLog()
    )
    assert result.failed_steps == (0,)


# --- the dirty-tree gate --------------------------------------------------------


def test_a_clean_tree_is_declarable_and_produces_no_warnings():
    state = RepoState(commit=COMMIT, dirty=False)
    assert state.declarable
    assert assert_declarable(state, counted=True) == []
    assert assert_declarable(state, counted=False) == []


def test_a_counted_series_refuses_to_start_on_a_dirty_tree():
    state = RepoState(commit=COMMIT, dirty=True, dirty_paths=("src/x.py",))
    with pytest.raises(DirtyWorkingTreeError, match="refusing to start a COUNTED series"):
        assert_declarable(state, counted=True)


def test_a_friendly_only_warns_on_a_dirty_tree():
    """Warm-ups are encouraged and owe no report to anyone, so a dirty tree
    costs nothing there."""
    state = RepoState(commit=COMMIT, dirty=True, dirty_paths=("src/x.py",))
    warnings = assert_declarable(state, counted=False)
    assert len(warnings) == 1
    assert "src/x.py" in warnings[0]


def test_an_undeterminable_commit_also_refuses_a_counted_series():
    with pytest.raises(DirtyWorkingTreeError, match="could not be determined"):
        assert_declarable(RepoState(commit=None, dirty=False), counted=True)


def test_an_unreadable_status_counts_as_dirty_not_clean(monkeypatch):
    """A wrong "clean" is a false declaration nobody can see; a wrong "dirty"
    is a refusal someone can read and act on."""
    import uoh_mh01.shared.build_commit as bc

    monkeypatch.setattr(bc, "_git", lambda args, cwd: COMMIT if args[0] == "rev-parse" else None)
    assert repo_state().dirty is True


def test_status_parsing_keeps_the_whole_path(monkeypatch):
    """`git status --porcelain` lines are `XY<space>path`. Stripping the raw
    output first eats the leading status column of the FIRST line only, which
    truncates exactly one path by one character and looks like a typo."""
    import uoh_mh01.shared.build_commit as bc

    porcelain = " M config/police/game.toml\n M src/uoh_mh01/__main__.py\n?? league/\n"
    monkeypatch.setattr(bc, "_git", lambda args, cwd: COMMIT if args[0] == "rev-parse" else porcelain)
    assert repo_state().dirty_paths == ("config/police/game.toml", "src/uoh_mh01/__main__.py", "league/")


def test_git_absence_is_reported_not_crashed(monkeypatch):
    import uoh_mh01.shared.build_commit as bc

    monkeypatch.setattr(bc, "_git", lambda args, cwd: None)
    assert repo_state() == RepoState(commit=None, dirty=False)


def test_a_non_repository_directory_yields_no_commit(tmp_path):
    """Real subprocess, no monkeypatch: git run outside a checkout must return
    None rather than raising into the caller."""
    assert current_commit_hash(str(tmp_path)) is None


def test_this_repo_reports_a_real_commit():
    assert repo_state().commit, "these tests run inside a git checkout"


# --- the report picks it up -----------------------------------------------------


def _log(n: int, commit: str | None) -> dict:
    payload = build_step_zero_payload(
        spec={}, code_version="0.1.0", group_name="us", sub_game_number=n, github_commit=commit
    )
    return {
        "summary": {
            "sub_game_number": n,
            "role": "police" if n % 2 else "thief",
            "result": "survival",
            "winner_role": "thief",
            "offending_side": None,
            "started_at": "2026-08-24T09:00:00+00:00",
            "ended_at": "2026-08-24T09:04:00+00:00",
            "audit": {"passed": True, "verified_steps": 34, "failed_steps": [], "reason": None},
        },
        "records": [{"step": 0, "payload": payload, "nonce": "n", "commit": "c"}],
    }


def test_the_report_populates_our_commit_for_every_sub_game(config_factory):
    """The end of the wire: a two-group series (ids differ, as in any real
    game) must carry our commit in every row."""
    declaration = {
        "game_id": "them-vs-us",
        "game_uid": "uid",
        "groups": {
            "mine": {"group_id": "uoh-mh01"},
            "opponent": {"group_id": "ali-ahm1", "github_commit": "9c17b5a9"},
        },
    }
    rows = sub_game_rows(declaration, [_log(n, COMMIT) for n in (1, 2, 3)], config_factory(), own_tokens=0)
    assert [r["github_commit"]["uoh-mh01"] for r in rows] == [COMMIT] * 3
    assert [r["github_commit"]["ali-ahm1"] for r in rows] == ["9c17b5a9"] * 3


def test_our_own_value_survives_a_group_id_collision(config_factory):
    """Self-play makes both ids identical and collapses the dict. Our real
    value must win over the opponent block's absent one."""
    declaration = {
        "game_id": "us-vs-us",
        "game_uid": "uid",
        "groups": {"mine": {"group_id": "uoh-mh01"}, "opponent": {"group_id": "uoh-mh01"}},
    }
    rows = sub_game_rows(declaration, [_log(1, COMMIT)], config_factory(), own_tokens=0)
    assert rows[0]["github_commit"]["uoh-mh01"] == COMMIT


def test_a_series_that_predates_the_field_still_reports_none(config_factory):
    """No backfilling: a series played before we sealed the commit reports
    null, not the version we happen to be on now."""
    old = _log(1, None)
    del old["records"][0]["payload"]["github_commit"]
    assert _own_github_commit(old) is None


def test_the_ali_ahm1_series_was_not_backfilled():
    """It was played before this change; its rows must stay null."""
    result = Path(__file__).resolve().parents[1] / "logs" / "result_ali-ahm1-vs-uoh-mh01.json"
    if not result.is_file():
        pytest.skip("no ali-ahm1 result artifact on disk")
    rows = json.loads(result.read_text(encoding="utf-8"))["sub_games"]
    assert all(row["github_commit"]["uoh-mh01"] is None for row in rows)
