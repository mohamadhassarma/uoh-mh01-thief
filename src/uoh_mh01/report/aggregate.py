"""Series aggregation: per-sub-game scores summed into the `final_result`
block, plus the one genuinely contested rule in the whole report.

DERIVED, NEVER DECLARED. Every total here is the plain sum of rows the two
peers already agreed on during PRD-03's audits. There is deliberately no way
to pass a precomputed total in: a second, independently computed total is a
second source of truth, and it will eventually disagree with the first
(interop kit SPEC §6).
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# THE TIE RULE. The book (ch.9 "כלל התיקו" / App. F table 17 row 5) and the
# reference implementation genuinely disagree about where App. F's `tie_score`
# lands on a TIED SERIES, and the interop kit documents three live behaviours:
#
#   series_add     — add tie_score to BOTH totals on a tied series (25/25 -> 27/27)
#   series_replace — REPLACE both totals with tie_score        (25/25 ->   2/2)
#   per_subgame    — no series-level adjustment at all; tied ROWS already paid
#                    2 each (the reference's own emit.py)      (25/25 -> 25/25)
#
# This project adopts SERIES_ADD, matching the interop kit's documented choice
# and its reasoning: App. E rule 35 charges BOTH teams for a contradictory
# report, so holding a minority reading privately risks an innocent opponent;
# and paying a fought 25-25 series only 2 while a single narrow 20-5 win pays
# 20 would rank one clean win above six hard-fought draws, inverting what the
# tie rule is plainly for.
#
# MUST BE DECLARED TO AN OPPONENT BEFORE ANY COUNTED SERIES. This is invisible
# in testing and in most series, and surfaces exactly once: the one time a
# real series ties. See PRD-07.
# ---------------------------------------------------------------------------
TIE_RULE = "series_add"


def score_rows(sub_games: list[dict[str, Any]], group_ids: list[str]) -> dict[str, int]:
    """Plain per-group sum of the per-sub-game `score` maps."""
    return {gid: sum(row["score"].get(gid, 0) for row in sub_games) for gid in group_ids}


def aggregate(sub_games: list[dict[str, Any]], group_ids: list[str], tie_score: int) -> dict[str, Any]:
    """The `final_result` core: totals, wins, ties, winner, series-tie flag."""
    totals = score_rows(sub_games, group_ids)
    wins = {gid: sum(1 for row in sub_games if row["winner_group"] == gid) for gid in group_ids}
    ties = sum(1 for row in sub_games if row["winner_group"] is None)

    series_tie = len(set(totals.values())) == 1 and len(totals) > 1
    if series_tie and TIE_RULE == "series_add":
        totals = {gid: total + tie_score for gid, total in totals.items()}

    winner_group = None if series_tie else max(totals, key=lambda gid: totals[gid])
    # EXACTLY the reference's five keys, in its order
    # (`ref_impl` domain/scoring.py:60-74). This block goes INSIDE the signed
    # consensus scope, so any key we add here that the reference does not emit
    # makes our signature differ from a conformant opponent's even when every
    # number agrees — a settlement failure with no visible cause. `tie_rule` is
    # declared in `final_result` instead, which is outside the scope.
    return {
        "total_score": totals,
        "sub_games_won": wins,
        "ties": ties,
        "winner_group": winner_group,
        "series_tie": series_tie,
    }


def tokens_total_series(sub_games: list[dict[str, Any]], group_ids: list[str]) -> dict[str, int | None]:
    """Book §9 requires the total tokens consumed. A group that never DECLARED
    its consumption totals to None, not 0 — summing an unclaimed count as zero
    would turn "they told us nothing" into "they told us they spent nothing",
    which is a fabricated declaration about someone else (App. E rules 37/38).
    """
    totals: dict[str, int | None] = {}
    for gid in group_ids:
        claimed = [row.get("tokens", {}).get(gid) for row in sub_games]
        totals[gid] = None if any(value is None for value in claimed) else sum(claimed)
    return totals


def diversity_reward(aggregate_block: dict[str, Any], group_ids: list[str], *, first_meeting: bool) -> dict[str, bool]:
    """App. F: 10 points for a WIN against a group not previously played — not
    merely for meeting one.

    DERIVED, never settable: `true` only for the winner of a genuine first
    counted meeting. The league table applies the points from this flag; it is
    explicitly NOT baked into `total_score` (PRD-07).
    """
    winner = aggregate_block["winner_group"]
    return {gid: bool(first_meeting and winner == gid) for gid in group_ids}
