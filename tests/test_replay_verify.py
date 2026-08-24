"""The book ch.7 replay verifier.

The thing that must not happen here is a viewer that says "Verified OK" for
everything. So most of these tests break something on purpose and check that
it is caught, and the two that do pass are pinned against the REAL ali-ahm1
artifacts rather than a fixture written to agree with the implementation.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from uoh_mh01.domain.crypto import commit_of, seal
from uoh_mh01.replay.verify import (
    VERDICT_OK,
    VERDICT_TAMPERED,
    commits_as_received,
    verify_series,
    verify_sub_game,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
REAL_LOGS = REPO_ROOT / "logs"
REAL_GAME_ID = "ali-ahm1-vs-uoh-mh01"


def _record(step: int, **extra):
    payload = {"step": step, "role": "police", "action_type": "move", "detail": "N", **extra}
    sealed = seal(payload)
    return {"payload": payload, "nonce": sealed["nonce"], "commit": sealed["commit"], "step": step}


def _log(records, **summary):
    return {"game_id": "them-vs-us", "game_uid": "uid-1", "summary": {"sub_game_number": 1, **summary}, "records": records}


def test_an_intact_sub_game_verifies():
    verdict = verify_sub_game(_log([_record(1), _record(2), _record(3)]))
    assert verdict.ok
    assert verdict.verdict == VERDICT_OK
    assert verdict.audit.verified_steps == 3


def test_an_edited_payload_is_caught():
    """The classic tamper: rewrite what was played, leave the commit alone."""
    records = [_record(1), _record(2)]
    records[1]["payload"]["detail"] = "S"
    verdict = verify_sub_game(_log(records))
    assert not verdict.ok
    assert verdict.verdict == VERDICT_TAMPERED
    assert verdict.audit.failed_steps == (2,)


def test_an_edited_commit_is_caught():
    records = [_record(1)]
    records[0]["commit"] = "0" * 64
    assert not verify_sub_game(_log(records)).ok


def test_a_wholly_removed_record_is_the_honest_limit_of_this_check():
    """Deleting a record OUTRIGHT is not detectable from the artifact alone,
    and this pins that limit rather than leaving it to be discovered later.

    Live, `infra/audit.py` catches exactly this, because it holds the commits
    that arrived over the wire and can see a step it received but was never
    shown. A replay has only the file, so removing a record removes it from
    both sides of the comparison at once. What a replay proves is that nothing
    was EDITED - which is what ch.7 asks it for.
    """
    records = [_record(1), _record(2), _record(3)]
    del records[1]
    verdict = verify_sub_game(_log(records))
    assert verdict.audit.verified_steps == 2
    # Nothing here can know step 2 ever existed, so this is the honest limit of
    # a self-consistency replay: it catches edits, not omissions of the whole
    # record. Pinned so the limit is stated rather than discovered later.
    assert verdict.ok


def test_an_empty_chain_does_not_pass():
    """An audit that verified nothing has no failures. That must not read as a
    pass - it is exactly what a broken peer produces."""
    verdict = verify_sub_game(_log([]))
    assert not verdict.ok
    assert "no steps verified" in verdict.audit.reason


# --- step 0 --------------------------------------------------------------------


def test_step_zero_is_verified_but_not_counted_as_a_played_step():
    payload = {"step": 0, "type": "system_spec", "code_version": "0.1.0"}
    sealed = seal(payload)
    step_zero = {"payload": payload, "nonce": sealed["nonce"], "commit": sealed["commit"], "step": 0}
    verdict = verify_sub_game(_log([step_zero, _record(1), _record(2)]))

    assert verdict.ok
    assert verdict.step_zero_present
    assert verdict.records == 3
    # Three records, two played steps: step 0 was never a turn.
    assert verdict.audit.verified_steps == 2


def test_a_tampered_step_zero_is_still_caught():
    """Disclosure-only does not mean unchecked: it is self-consistent or it is
    not, and a rewritten host spec or commit hash is a false declaration."""
    payload = {"step": 0, "type": "system_spec", "github_commit": "a" * 40}
    sealed = seal(payload)
    payload["github_commit"] = "b" * 40
    records = [{"payload": payload, "nonce": sealed["nonce"], "commit": sealed["commit"], "step": 0}, _record(1)]
    verdict = verify_sub_game(_log(records))
    assert not verdict.ok
    assert 0 in verdict.audit.failed_steps


def test_step_zero_is_kept_out_of_the_expected_step_count():
    """If step 0 were counted as a played step, the verdict floor would expect
    one more step than was ever played and every honest series would fail."""
    payload = {"step": 0, "type": "system_spec"}
    sealed = seal(payload)
    records = [{"payload": payload, "nonce": sealed["nonce"], "commit": sealed["commit"], "step": 0}, _record(1)]
    assert 0 not in commits_as_received(records).by_step
    assert set(commits_as_received(records).by_step) == {1}


# --- the hashing is the audit module's, not a second copy -----------------------


def test_the_recomputed_hash_is_the_projects_own_commit_function():
    """A second SHA-256 implementation in the viewer would prove nothing about
    the first if it agreed, and would report an honest series as tampered if it
    did not."""
    record = _record(4)
    assert commit_of(record["payload"], record["nonce"]) == record["commit"]
    assert verify_sub_game(_log([record])).ok


# --- against the real series on disk --------------------------------------------


@pytest.mark.skipif(
    not (REAL_LOGS / f"declaration_{REAL_GAME_ID}.json").is_file(),
    reason="the ali-ahm1 artifacts are not in this checkout",
)
class TestTheRealSeries:
    """Counts are deliberately NOT asserted here. Both repos run this file
    byte-identically and they hold different slices of the ali-ahm1 series, so
    a hard-coded "6 sub-games" would pass in one and fail in the other for a
    reason that has nothing to do with the verifier."""

    def test_the_played_series_verifies(self):
        verdict = verify_series(REAL_LOGS, REAL_GAME_ID)
        assert verdict.sub_games, "no sub-game logs were read at all"
        assert verdict.ok, [s.audit.reason for s in verdict.sub_games if not s.ok]
        assert verdict.verified_steps > 0

    def test_every_sub_game_declares_a_step_zero(self):
        verdict = verify_series(REAL_LOGS, REAL_GAME_ID)
        assert all(sub.step_zero_present for sub in verdict.sub_games)
        # One record per sub-game is step 0, so records always exceed steps.
        assert all(sub.records == sub.audit.verified_steps + 1 for sub in verdict.sub_games)

    def test_tampering_with_a_copy_of_the_real_series_is_detected(self, tmp_path):
        for artifact in REAL_LOGS.glob(f"*{REAL_GAME_ID}*"):
            (tmp_path / artifact.name).write_bytes(artifact.read_bytes())
        target = sorted(tmp_path.glob(f"log_{REAL_GAME_ID}_g*.json"))[-1]
        log = json.loads(target.read_text(encoding="utf-8"))
        edited = None
        for record in log["records"]:
            if record["payload"].get("action_type") == "move":
                record["payload"]["detail"] = "N" if record["payload"]["detail"] != "N" else "S"
                edited = log["summary"]["sub_game_number"]
                break
        assert edited is not None, "no move record to tamper with"
        target.write_text(json.dumps(log), encoding="utf-8")

        verdict = verify_series(tmp_path, REAL_GAME_ID)
        assert verdict.verdict == VERDICT_TAMPERED
        failed = [sub.sub_game_number for sub in verdict.sub_games if not sub.ok]
        assert failed == [edited], "only the edited sub-game should fail"
