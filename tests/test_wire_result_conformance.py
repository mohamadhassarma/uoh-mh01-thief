"""The result string that leaves this process.

WHY THIS FILE EXISTS. We emitted `"capture_landing"` - a name that appears in
no book, no reference and no interop vector - as `result_claim` on the wire and
as `summary.result` in the log artifact, for six sub-games against a live
opponent. The reference emits `"capture"` (ref_impl domain/scoring.py:13,
peer/runtime.py:122/:127) and its `score_subgame` scores anything that is not
capture/survival as a technical loss, 0/0 to both sides. Two honest peers would
therefore have described one sub-game two ways, which is the contradictory
report App. E rule 35 zeroes both teams for.

Nothing in the suite could see it: every test asserted our own vocabulary
against itself. So these tests assert against the LEAGUE's vocabulary, taken
from `docs/WIRE.md` (which had it right all along) and the reference.
"""

from __future__ import annotations

import inspect
import json
import re
from pathlib import Path

import pytest

from uoh_mh01.domain.config import load_config
from uoh_mh01.domain.scoring import (
    LEGACY_CAPTURE_RESULTS,
    WIRE_CAPTURE,
    WIRE_RESULTS,
    TerminalCondition,
    is_capture_result,
    score_for,
    score_for_result,
    to_wire_result,
)
from uoh_mh01.domain.sealed_payload import build_audit_payload
from uoh_mh01.infra.artifacts import LogArtifactBuilder

REPO_ROOT = Path(__file__).resolve().parents[1]
SCORING = load_config(REPO_ROOT / "config" / "game.json").scoring

CAPTURES = (
    TerminalCondition.CAPTURE_LANDING,
    TerminalCondition.CAPTURE_BARRIER,
    TerminalCondition.CAPTURE_ENTRAPMENT,
)
INTERNAL_NAMES = tuple(condition.value for condition in CAPTURES)


# --- the projection -------------------------------------------------------------


@pytest.mark.parametrize("condition", CAPTURES)
def test_every_capture_family_leaves_as_the_league_s_single_word(condition):
    """SPEC.md:153-190 names three capture families - co-location, rule 46,
    rule 47 - and says all three "settle CAPTURE". The distinction lives in
    `claim_response`, not in the result string."""
    assert to_wire_result(condition) == WIRE_CAPTURE


@pytest.mark.parametrize(
    "condition", [TerminalCondition.SURVIVAL, TerminalCondition.TECHNICAL_LOSS, TerminalCondition.TIE]
)
def test_non_captures_are_projected_unchanged(condition):
    assert to_wire_result(condition) == condition.value


def test_no_condition_can_project_to_an_internal_capture_name():
    """The property, over the whole enum, so a fourth capture family added
    later cannot quietly reintroduce this."""
    assert not [c for c in TerminalCondition if to_wire_result(c) in INTERNAL_NAMES]


def test_the_internal_taxonomy_is_kept():
    """Only the emitted string changed. The three families are a real
    distinction and they stay - we simply stopped exporting them."""
    assert {c.value for c in CAPTURES} == {"capture_landing", "capture_barrier", "capture_entrapment"}
    assert len({to_wire_result(c) for c in CAPTURES}) == 1, "...but they are indistinguishable on the wire"


# --- what actually leaves the process -------------------------------------------


@pytest.mark.parametrize("condition", CAPTURES)
def test_neither_the_wire_payload_nor_the_log_artifact_carries_an_internal_name(condition):
    """The two surfaces the one `result_str` assignment feeds."""
    wire = to_wire_result(condition)
    payload = build_audit_payload(sender="police", records=[], result_claim=wire)
    log = LogArtifactBuilder(
        game_id="g", game_uid="u", sub_game_number=1, role="police",
        group_id="a", opponent_group_id="b", started_at="2026-08-24T00:00:00+00:00",
    ).build(
        result=wire, winner_role="police", offending_side=None, steps=1,
        audit_of_opponent_passed=True, audit_verified_steps=1, audit_failed_steps=[],
    )

    assert payload["result_claim"] == WIRE_CAPTURE
    assert log["summary"]["result"] == WIRE_CAPTURE
    serialised = json.dumps(payload, ensure_ascii=False) + json.dumps(log, ensure_ascii=False)
    assert not [name for name in INTERNAL_NAMES if name in serialised]


def test_the_emitted_value_is_in_the_documented_wire_vocabulary():
    """`docs/WIRE.md` documented `result_claim` correctly from the start, citing
    the reference's `protocol.py:74`. Only the code disagreed, so this pins the
    code to the doc."""
    row = next(
        line for line in (REPO_ROOT / "docs" / "WIRE.md").read_text(encoding="utf-8").splitlines()
        if line.strip().startswith("| `result_claim`")
    )
    documented = set(re.findall(r'"([a-z_]+)"', row))
    assert WIRE_CAPTURE in documented
    assert not documented & set(INTERNAL_NAMES)
    assert to_wire_result(TerminalCondition.CAPTURE_LANDING) in documented
    assert to_wire_result(TerminalCondition.SURVIVAL) in documented


def test_the_single_emit_point_uses_the_projection_not_dot_value():
    """One assignment in `play_one_sub_game` feeds both the wire and the log
    artifact. It used `.value`, which is how this shipped."""
    from uoh_mh01.infra import series_subgame

    source = inspect.getsource(series_subgame.play_one_sub_game)
    emit = next(line for line in source.splitlines() if "result_str, winner_role =" in line)
    assert "to_wire_result(" in emit
    assert ".value" not in emit


# --- receiving, tolerantly ------------------------------------------------------


@pytest.mark.parametrize("result", [WIRE_CAPTURE, *sorted(LEGACY_CAPTURE_RESULTS)])
def test_both_vocabularies_are_recognised_as_a_capture(result):
    assert is_capture_result(result)


@pytest.mark.parametrize("result", [WIRE_CAPTURE, *sorted(LEGACY_CAPTURE_RESULTS)])
def test_both_vocabularies_score_identically(result):
    """They describe the same event, so they must be worth the same. Our own
    artifacts written before this fix still have to read back correctly."""
    assert score_for_result(result, SCORING) == score_for(TerminalCondition.CAPTURE_LANDING, SCORING)
    assert score_for_result(result, SCORING) == (SCORING.capture_cop, SCORING.capture_thief)


def test_survival_is_unaffected():
    assert score_for_result("survival", SCORING) == (SCORING.survival_cop, SCORING.survival_thief)


def test_an_unknown_result_scores_zero_rather_than_raising(caplog):
    """The reference's own rule: anything that is not capture/survival is a
    technical loss (ref_impl domain/scoring.py:25-31). Raising instead would
    let one unfamiliar string from an opponent stop us reporting a series we
    really played - and `"undefined"` and `"disputed"`, which our own runner
    can produce, used to do exactly that."""
    assert score_for_result("their_internal_name", SCORING) == (SCORING.technical_loss, SCORING.technical_loss)
    assert score_for_result("undefined", SCORING) == (0, 0)
    assert "unrecognised result string" in caplog.text


def test_an_unknown_result_is_not_mistaken_for_a_capture():
    assert not is_capture_result("captured")
    assert not is_capture_result("capture_")
    assert not is_capture_result("")


# --- our own history still reads ------------------------------------------------


@pytest.mark.skipif(
    not sorted(REPO_ROOT.glob("logs/log_*_g01.json")), reason="no series artifacts in this checkout"
)
def test_every_artifact_on_disk_still_reads_and_scores():
    """Includes the series we played emitting the old name. Tolerance is not
    theoretical here - these files exist and a report is still owed on one.

    Two separate claims: every stored result string still scores (the string
    layer), and `sub_game_rows` still builds a report row for every series on
    disk without raising (the report layer, which used to call
    `TerminalCondition(...)` and would now blow up on the new `"capture"`).
    """
    from uoh_mh01.report.series_reader import load_series, sub_game_rows

    config = load_config(REPO_ROOT / "config" / "game.json")
    seen = set()
    for declaration in sorted(REPO_ROOT.glob("logs/declaration_*.json")):
        game_id = declaration.name[len("declaration_"):-len(".json")]
        declaration_doc, log_docs = load_series(REPO_ROOT / "logs", game_id)
        rows = sub_game_rows(declaration_doc, log_docs, config, own_tokens=0)
        assert len(rows) == len(log_docs), f"{game_id}: a sub-game produced no report row"
        for log in log_docs:
            result = log["summary"]["result"]
            seen.add(result)
            if is_capture_result(result):
                assert score_for_result(result, SCORING) == (SCORING.capture_cop, SCORING.capture_thief)

    assert seen, "no results were read at all"
    # The point of the exercise: the old name is really on disk, in real
    # artifacts, and still reads.
    assert seen & LEGACY_CAPTURE_RESULTS, "expected at least one pre-fix artifact to exercise tolerance"


# --- the guard at the door ------------------------------------------------------


@pytest.mark.parametrize("surface", ["wire", "artifact"])
def test_emitting_an_internal_name_warns_at_the_boundary(surface, caplog):
    """A guard where the string actually crosses, not a rule in a docstring.
    Had this existed, the six `capture_landing` reveals that reached a live
    opponent would each have said so."""
    if surface == "wire":
        build_audit_payload(sender="police", records=[], result_claim="capture_landing")
    else:
        LogArtifactBuilder(
            game_id="g", game_uid="u", sub_game_number=1, role="police",
            group_id="a", opponent_group_id="b", started_at="2026-08-24T00:00:00+00:00",
        ).build(
            result="capture_landing", winner_role="police", offending_side=None, steps=1,
            audit_of_opponent_passed=True, audit_verified_steps=1, audit_failed_steps=[],
        )
    assert "non-league result string" in caplog.text
    assert "capture_landing" in caplog.text


@pytest.mark.parametrize("result", sorted(WIRE_RESULTS))
def test_a_conforming_string_passes_the_guard_silently(result, caplog):
    build_audit_payload(sender="police", records=[], result_claim=result)
    assert "non-league" not in caplog.text


def test_the_guard_warns_but_never_raises():
    """A wrong label on a sub-game that was really played is bad. Forfeiting
    that sub-game to an exception mid-series is worse."""
    payload = build_audit_payload(sender="police", records=[], result_claim="something_nobody_uses")
    assert payload["result_claim"] == "something_nobody_uses", "it must still emit, having warned"


def test_every_projection_output_passes_the_guard():
    """The projection and the guard must agree, or one of them is wrong."""
    assert {to_wire_result(c) for c in TerminalCondition} <= WIRE_RESULTS
