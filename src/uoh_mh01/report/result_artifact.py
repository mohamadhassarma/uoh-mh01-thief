"""`result_<game_id>.json` — the fourth standardized artifact (book App. F
table 20), and the one the lecturer actually grades from.

THE BOOK'S MANDATORY CONTENT (§9, verified against the PDF): "השדות המחייבים
בדוח כוללים את קישורי ה-GitHub של שתי הקבוצות, את מזהה הקומיט של כל משחקון,
ואת סך הטוקנים שנצרכו" — both groups' GitHub links, the commit id of EVERY
sub-game, and the total tokens consumed. Plus each group's score in each
sub-game and the cumulative result, and the shared `game_uid`/`game_id`.

SHAPE. The reference's own `report/artifacts.py::build_result` supplies the
skeleton, because that is what the lecturer's tooling reads. ONE addition:
`links.github`, which the reference omits and the book requires — the interop
kit adds it in the same place ("Rule 49: the result carries the repo links",
`sparring/artifacts.py:148-151`), so the two outside sources between them
cover the book's requirement and nothing here is invented.
"""

from __future__ import annotations

from typing import Any

from .aggregate import TIE_RULE, aggregate, diversity_reward, tokens_total_series
from .consensus import consensus_signature, symmetric_scope

SCHEMA_VERSION = "1.1"
REPORT_TYPE = "final_game_result"


def _links(game_id: str, declaration: dict[str, Any], group_ids: list[str]) -> dict[str, Any]:
    repos = {
        gid: block["repos"]
        for gid, block in _identity_blocks(declaration).items()
        if gid in group_ids and block.get("repos")
    }
    links: dict[str, Any] = {
        "declaration": f"declaration_{game_id}.json",
        "config": f"config_{game_id}_g<NN>.json",
        "log": f"log_{game_id}_g<NN>.json",
        "result": f"result_{game_id}.json",
    }
    # Book §9's "GitHub links of BOTH groups". Only groups that actually
    # declared repos appear — an opponent that sent none is not invented for.
    if repos:
        links["github"] = repos
    return links


def _identity_blocks(declaration: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {block["group_id"]: block for block in declaration["groups"].values()}


def build_result(
    declaration: dict[str, Any],
    sub_games: list[dict[str, Any]],
    config,
    *,
    first_meeting: bool,
    games_played_including_this: dict[str, int | None],
) -> dict[str, Any]:
    """The whole artifact. Every total is derived from `sub_games`; there is no
    parameter through which a precomputed total could be supplied."""
    game_id, game_uid = declaration["game_id"], declaration["game_uid"]
    group_ids = sorted(_identity_blocks(declaration))
    agg = aggregate(sub_games, group_ids, config.scoring.tie_score)
    final_result = {
        **agg,
        # Declared in the report but NOT under the consensus hash: it names the
        # reading we used so an opponent can diff it against theirs in words
        # rather than discovering the disagreement as an opaque hash mismatch.
        "tie_rule": TIE_RULE,
        "tokens_total_series": tokens_total_series(sub_games, group_ids),
        "first_meeting_between_groups": first_meeting,
        "diversity_reward_applied": diversity_reward(agg, group_ids, first_meeting=first_meeting),
        "games_played_including_this": games_played_including_this,
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "report_type": REPORT_TYPE,
        "game_id": game_id,
        "game_uid": game_uid,
        "links": _links(game_id, declaration, group_ids),
        "groups": group_ids,
        "num_sub_games": len(sub_games),
        "sub_games": sub_games,
        "final_result": final_result,
        "mutual_agreement": {
            # Over the TRIMMED symmetric scope, not this whole document — see
            # consensus.symmetric_scope for why a whole-body hash could never
            # match between two honest peers.
            "sha256": consensus_signature(symmetric_scope(game_id, agg, sub_games)),
            "confirmed": all(row["audit"]["log_verified"] for row in sub_games),
        },
    }


def verify_mutual_agreement(result: dict[str, Any]) -> bool:
    """Recompute the signature from the document's own rows. This is what an
    opponent's copy is checked against at settlement."""
    scope = symmetric_scope(result["game_id"], _aggregate_core(result), result["sub_games"])
    return consensus_signature(scope) == result["mutual_agreement"]["sha256"]


def _aggregate_core(result: dict[str, Any]) -> dict[str, Any]:
    """The `aggregate` block as it was hashed — `final_result` minus the
    fields added after signing."""
    excluded = {
        "tie_rule",
        "tokens_total_series",
        "first_meeting_between_groups",
        "diversity_reward_applied",
        "games_played_including_this",
    }
    return {k: v for k, v in result["final_result"].items() if k not in excluded}
