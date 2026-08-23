"""`result_<game_id>.json`: the book's mandatory content, derived totals, the
tie rule, and the gates that keep a warm-up away from the lecturer.

Book §9 makes three things mandatory: both groups' GitHub links, the commit id
of EVERY sub-game, and the total tokens consumed. Those get their own tests
because a report that omits them is rejected, and rejection costs the round's
league points.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from uoh_mh01.domain.config import load_config
from uoh_mh01.report import ledger, pipeline
from uoh_mh01.report.aggregate import TIE_RULE, aggregate, diversity_reward, tokens_total_series
from uoh_mh01.report.result_artifact import build_result, verify_mutual_agreement
from uoh_mh01.report.series_reader import SeriesNotFoundError, load_series, sub_game_rows

CONFIG = load_config(Path(__file__).resolve().parents[1] / "config" / "game.json")


def _row(n, own_score, opp_score, winner, *, own="us", opp="them", commit="c0ffee", tokens=0):
    return {
        "sub_game_number": n,
        "roles": {own: "police", opp: "thief"},
        "started_at": "2026-08-23T20:01:44+00:00",
        "ended_at": "2026-08-23T20:04:02+00:00",
        "result": "survival",
        "winner_group": winner,
        "tie": winner is None,
        "github_commit": {own: commit, opp: commit},
        "tokens": {own: tokens, opp: tokens},
        "score": {own: own_score, opp: opp_score},
        "log_files": {own: f"log_x_g{n:02d}.json"},
        "audit": {"log_verified": True, "verified_steps": 34, "failed_steps": [], "tampered": False},
    }


def _declaration(**overrides):
    base = {
        "game_id": "them-vs-us",
        "game_uid": "feb39143-b9e2-850f-bbb1-a58be0f5d9cc",
        "groups": {
            "mine": {"group_id": "us", "repos": {"cop": "https://example.invalid/us"}},
            "opponent": {"group_id": "them", "repos": {"cop": "https://example.invalid/them"}},
        },
    }
    return {**base, **overrides}


def _build(rows, **kwargs):
    return build_result(
        _declaration(), rows, CONFIG, first_meeting=kwargs.pop("first_meeting", True),
        games_played_including_this=kwargs.pop("games", {"us": 1, "them": None}),
    )


# --- book §9 mandatory content --------------------------------------------------


def test_the_result_carries_both_groups_github_links():
    result = _build([_row(1, 5, 10, "them")])
    assert set(result["links"]["github"]) == {"us", "them"}


def test_every_sub_game_carries_a_commit_id_for_both_groups():
    result = _build([_row(1, 5, 10, "them"), _row(2, 10, 5, "us")])
    for row in result["sub_games"]:
        assert set(row["github_commit"]) == {"us", "them"}


def test_the_result_carries_the_series_token_total_and_the_two_ids():
    result = _build([_row(1, 5, 10, "them")])
    assert result["final_result"]["tokens_total_series"] == {"us": 0, "them": 0}
    assert result["game_uid"] and result["game_id"]


def test_an_undeclared_token_count_totals_to_none_not_zero():
    """"They told us nothing" must not become "they told us they spent
    nothing" — that is a fabricated declaration about someone else."""
    rows = [_row(1, 5, 10, "them")]
    rows[0]["tokens"]["them"] = None
    assert tokens_total_series(rows, ["us", "them"]) == {"us": 0, "them": None}


# --- derived, never declared ----------------------------------------------------


def test_totals_are_the_plain_sum_of_the_rows():
    rows = [_row(1, 5, 10, "them"), _row(2, 10, 5, "us"), _row(3, 20, 5, "us")]
    assert _build(rows)["final_result"]["total_score"] == {"us": 35, "them": 20}


def test_no_parameter_exists_through_which_a_total_could_be_supplied():
    import inspect

    names = set(inspect.signature(build_result).parameters)
    assert not {"total_score", "totals", "final_result", "aggregate"} & names


def test_the_diversity_reward_is_derived_from_the_outcome_not_settable():
    agg = aggregate([_row(1, 20, 5, "us")], ["us", "them"], CONFIG.scoring.tie_score)
    assert diversity_reward(agg, ["us", "them"], first_meeting=True) == {"us": True, "them": False}
    # A repeat pairing pays nobody, even the winner.
    assert diversity_reward(agg, ["us", "them"], first_meeting=False) == {"us": False, "them": False}


# --- the tie rule ---------------------------------------------------------------


def test_a_tied_series_adds_tie_score_to_both_totals():
    """`series_add`, the one contested rule. 45-45 becomes 47-47 with
    tie_score=2 — NOT 2-2 (series_replace) and NOT 45-45 (per_subgame)."""
    assert TIE_RULE == "series_add"
    rows = [_row(1, 5, 10, "them"), _row(2, 10, 5, "us")] * 3
    for n, row in enumerate(rows, start=1):
        row["sub_game_number"] = n
    final = _build(rows)["final_result"]
    assert final["total_score"] == {"us": 47, "them": 47}
    assert final["series_tie"] is True
    assert final["winner_group"] is None


def test_an_untied_series_pays_no_tie_score():
    final = _build([_row(1, 20, 5, "us")])["final_result"]
    assert final["total_score"] == {"us": 20, "them": 5}
    assert final["series_tie"] is False
    assert final["winner_group"] == "us"


# --- the consensus signature over a real result ---------------------------------


def test_the_result_self_verifies():
    assert verify_mutual_agreement(_build([_row(1, 5, 10, "them"), _row(2, 10, 5, "us")]))


def test_two_peers_differing_only_on_tokens_and_clocks_sign_identically():
    """The whole point of the trimmed scope. If this ever fails, settlement
    fails for two honest teams."""
    mine = [_row(1, 5, 10, "them")]
    theirs = [{**_row(1, 5, 10, "them"), "started_at": "2026-08-23T20:01:45+00:00", "tokens": {"us": 0, "them": 900}}]
    assert _build(mine)["mutual_agreement"]["sha256"] == _build(theirs)["mutual_agreement"]["sha256"]


def test_mutual_agreement_is_unconfirmed_when_any_audit_failed():
    rows = [_row(1, 5, 10, "them"), _row(2, 10, 5, "us")]
    rows[1]["audit"]["log_verified"] = False
    assert _build(rows)["mutual_agreement"]["confirmed"] is False


# --- reading a real series back off disk ----------------------------------------


def test_a_missing_series_is_a_clear_error_not_an_empty_report(tmp_path):
    with pytest.raises(SeriesNotFoundError):
        load_series(tmp_path, "nobody-vs-nobody")


def test_rows_are_keyed_by_group_id_because_roles_alternate(tmp_path):
    logs = Path(__file__).resolve().parents[1] / "logs"
    # Needs at least two sub-games to observe alternation at all. This repo's
    # sibling holds only sub-game 1 of that series, and a one-row skip guard
    # would have made this test assert something unobservable there.
    if len(list(logs.glob("log_ali-ahm1-vs-uoh-mh01_g*.json"))) < 2:
        pytest.skip("no multi-sub-game cross-team series on disk")
    declaration, sub_logs = load_series(logs, "ali-ahm1-vs-uoh-mh01")
    rows = sub_game_rows(declaration, sub_logs, CONFIG, own_tokens=0)
    assert {r["roles"]["uoh-mh01"] for r in rows} == {"police", "thief"}, "roles must alternate"
    for row in rows:
        assert set(row["score"]) == {"uoh-mh01", "ali-ahm1"}


# --- the ledger -----------------------------------------------------------------


def test_the_ledger_makes_a_repeat_pairing_visible(tmp_path):
    path = tmp_path / "counted_games.json"
    assert ledger.is_first_meeting("them", path=path)
    ledger.record_counted_series(
        opponent_group_id="them", game_id="them-vs-us", game_uid="uid-1", ended_at="now", path=path
    )
    assert not ledger.is_first_meeting("them", path=path)
    assert ledger.counted_games_played(path=path) == 1


def test_recording_the_same_series_twice_cannot_inflate_the_count(tmp_path):
    path = tmp_path / "counted_games.json"
    for _ in range(3):
        ledger.record_counted_series(
            opponent_group_id="them", game_id="them-vs-us", game_uid="uid-1", ended_at="now", path=path
        )
    assert ledger.counted_games_played(path=path) == 1


def test_the_ledger_is_committed_not_gitignored():
    """An uncommitted ledger cannot prove a repeat pairing to a grader who
    re-clones the repo (PRD-07)."""
    root = Path(__file__).resolve().parents[1]
    ignored = (root / ".gitignore").read_text(encoding="utf-8")
    assert "league/" not in ignored
    assert (root / "league" / "counted_games.json").is_file()


def test_a_recorded_ledger_round_trips_as_json(tmp_path):
    path = tmp_path / "counted_games.json"
    ledger.record_counted_series(
        opponent_group_id="them", game_id="g", game_uid="u", ended_at="now", path=path
    )
    assert json.loads(path.read_text(encoding="utf-8"))["counted_series"][0]["opponent_group_id"] == "them"


# --- the send gate --------------------------------------------------------------


def test_a_non_counted_run_refuses_before_touching_a_credential(tmp_path):
    from uoh_mh01.infra.gmail_sender import NotACountedRunError

    result = _build([_row(1, 5, 10, "them")])
    path = tmp_path / "result.json"
    path.write_text(json.dumps(result), encoding="utf-8")
    with pytest.raises(NotACountedRunError):
        # `service=None` would trigger the OAuth path if the gate were ever
        # reached — it must not be.
        pipeline.send_report(path, result, CONFIG, counted=False, sender="me")
