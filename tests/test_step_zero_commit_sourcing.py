"""Where the per-sub-game `github_commit` is read from.

WHY THIS FILE EXISTS. We read the OPPONENT's commit only from the negotiate
identity while emitting our own only in the sealed step-0 record - a double
standard, and the identity copy is a series headline anyway. Rule 53 binds the
PER-ROLE, PER-SUB-GAME commit, which only step-0 carries
(interop_kit/examples/gen_pairing_artifacts.py:194-196). Against khm-mn17,
whose identity omits the field and whose step-0 carries it, all six sub-games
reported null and the automatic send refused.

We also discarded their revealed chain after auditing it, so the value was not
merely unread - it was unreachable.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from uoh_mh01.domain.config import load_config
from uoh_mh01.domain.crypto import seal
from uoh_mh01.infra.artifacts import LogArtifactBuilder
from uoh_mh01.report.series_reader import step_zero_commit, sub_game_rows

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG = load_config(REPO_ROOT / "config" / "game.json")

OURS = "a" * 40
THEIRS = "b" * 40

# The reference's inline spelling - what we emit.
SYSTEM_SPEC = {"step": 0, "type": "system_spec", "spec": {}, "code_version": "0.1.0", "github_commit": THEIRS}
# The kit's slim spelling. SPEC 7.2: a reader must accept either.
STEP_ZERO = {"step": 0, "type": "step_zero", "declaration_ref": "declaration_x.json", "github_commit": THEIRS}


def _sealed(payload):
    s = seal(payload)
    return {"payload": payload, "nonce": s["nonce"], "commit": s["commit"], "step": payload.get("step", 0)}


def _move(step, commit=None):
    payload = {"step": step, "role": "police", "action_type": "move", "detail": "N"}
    if commit:
        payload["github_commit"] = commit
    return _sealed(payload)


# --- reading step-0 -------------------------------------------------------------


@pytest.mark.parametrize("spelling", [SYSTEM_SPEC, STEP_ZERO], ids=["system_spec", "step_zero"])
def test_both_conformant_step_zero_spellings_are_accepted(spelling):
    """They differ in `type`; both put step 0 and a top-level github_commit in
    the payload. The kit's own generator emits one of each in a single log."""
    assert step_zero_commit([_sealed(dict(spelling)), _move(1)]) == THEIRS


def test_a_chain_with_no_step_zero_yields_nothing_rather_than_a_guess():
    assert step_zero_commit([_move(1), _move(2)]) is None


def test_a_step_zero_carrying_no_commit_yields_nothing():
    assert step_zero_commit([_sealed({"step": 0, "type": "system_spec"})]) is None


def test_an_empty_or_absent_chain_is_safe():
    assert step_zero_commit([]) is None
    assert step_zero_commit(None) is None


def test_a_later_step_is_never_mistaken_for_step_zero():
    """A commit on a move record is not a step-0 declaration and must not be
    read as one - that would be reporting an unverified value."""
    assert step_zero_commit([_move(1, commit="c" * 40), _move(2)]) is None


# --- the artifact carries their chain -------------------------------------------


def test_the_log_artifact_persists_the_opponent_records():
    """Verified in memory and discarded is what made their commit unreachable."""
    builder = LogArtifactBuilder(
        game_id="g", game_uid="u", sub_game_number=1, role="police",
        group_id="us", opponent_group_id="them", started_at="2026-08-24T00:00:00+00:00",
    )
    builder.add_record(1, {"step": 1}, "n", "c")
    builder.opponent_records = [_sealed(dict(SYSTEM_SPEC))]
    doc = builder.build(
        result="survival", winner_role="thief", offending_side=None, steps=1,
        audit_of_opponent_passed=True, audit_verified_steps=1, audit_failed_steps=[],
    )
    assert doc["opponent_records"], "their chain must survive into the artifact"
    assert step_zero_commit(doc["opponent_records"]) == THEIRS
    assert doc["schema_version"] == "1.1"


def test_the_sub_game_writes_their_chain_into_the_builder():
    """A structural backstop: the reveal we already verify is the only copy."""
    import inspect

    from uoh_mh01.infra import series_subgame

    source = inspect.getsource(series_subgame.play_one_sub_game)
    assert "log_builder.opponent_records" in source
    assert "their_payload" in source


# --- the report row -------------------------------------------------------------


def _series(*, their_identity_commit=None, their_step_zero=True, n=2):
    declaration = {
        "game_id": "them-vs-us",
        "groups": {
            "mine": {"group_id": "us"},
            "opponent": {"group_id": "them", **({"github_commit": their_identity_commit} if their_identity_commit else {})},
        },
    }
    logs = []
    for i in range(1, n + 1):
        # A DIFFERENT commit per sub-game, so a reader that takes one series-level
        # value cannot pass by accident.
        ours, theirs = f"{i}{OURS[1:]}", f"{i}{THEIRS[1:]}"
        logs.append({
            "summary": {
                "sub_game_number": i, "role": "police", "group_id": "us", "opponent_group_id": "them",
                "result": "survival", "winner_role": "thief", "offending_side": None, "steps": 1,
                "started_at": "t", "ended_at": "t",
                "audit": {"passed": True, "verified_steps": 1, "failed_steps": []},
            },
            "records": [_sealed({"step": 0, "type": "system_spec", "github_commit": ours})],
            "opponent_records": (
                [_sealed({"step": 0, "type": "system_spec", "github_commit": theirs})] if their_step_zero else []
            ),
        })
    return declaration, logs


def test_their_commit_comes_from_their_step_zero_per_sub_game():
    declaration, logs = _series()
    rows = sub_game_rows(declaration, logs, CONFIG, own_tokens=0)
    assert [r["github_commit"]["them"] for r in rows] == [f"1{THEIRS[1:]}", f"2{THEIRS[1:]}"]


def test_our_commit_comes_from_our_step_zero_per_sub_game():
    declaration, logs = _series()
    rows = sub_game_rows(declaration, logs, CONFIG, own_tokens=0)
    assert [r["github_commit"]["us"] for r in rows] == [f"1{OURS[1:]}", f"2{OURS[1:]}"]


def test_the_identity_is_a_fallback_not_the_source():
    """When step-0 has it, the headline must not win - the headline is one value
    for a whole series and rule 53 binds the per-sub-game one."""
    declaration, logs = _series(their_identity_commit="headline" + "0" * 32)
    rows = sub_game_rows(declaration, logs, CONFIG, own_tokens=0)
    assert all(not r["github_commit"]["them"].startswith("headline") for r in rows)


def test_the_identity_still_rescues_a_peer_that_only_populates_it():
    """Peers that declare only in the identity must keep reporting."""
    headline = "d" * 40
    declaration, logs = _series(their_identity_commit=headline, their_step_zero=False)
    rows = sub_game_rows(declaration, logs, CONFIG, own_tokens=0)
    assert [r["github_commit"]["them"] for r in rows] == [headline, headline]


def test_a_peer_that_declares_it_nowhere_stays_null():
    """Absent stays absent. A fabricated hash is the false declaration App. E
    rules 37/38 punish."""
    declaration, logs = _series(their_step_zero=False)
    rows = sub_game_rows(declaration, logs, CONFIG, own_tokens=0)
    assert all(r["github_commit"]["them"] is None for r in rows)


def test_the_khm_mn17_series_is_not_backfilled():
    """Their chain was discarded before the fix and their commit only reaches us
    out of band. An unverified value in a graded report is the thing to avoid."""
    logs_dir = REPO_ROOT / "logs"
    declaration_path = logs_dir / "declaration_khm-mn17-vs-uoh-mh01.json"
    if not declaration_path.is_file():
        pytest.skip("the khm-mn17 series lives in the other repo")
    from uoh_mh01.report.series_reader import load_series

    declaration, logs = load_series(logs_dir, "khm-mn17-vs-uoh-mh01")
    rows = sub_game_rows(declaration, logs, CONFIG, own_tokens=0)
    assert all(row["github_commit"]["khm-mn17"] is None for row in rows)
    assert all(row["github_commit"]["uoh-mh01"] for row in rows), "ours still reads"
    assert not any("opponent_records" in json.dumps(log) for log in logs), "no chain to read"
