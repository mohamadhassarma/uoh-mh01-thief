"""Read a played series back off disk — the declaration plus every
`log_<game_id>_gNN.json` — and turn it into the per-sub-game rows the result
artifact aggregates.

Reads ONLY what PRD-03 already wrote and both peers already audited. Nothing
here recomputes an outcome: the row's `result`, `winner_role` and audit
verdict are lifted from the settled log, so the report cannot disagree with
the game it describes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..domain.config import GameConfig
from ..domain.scoring import score_for_result
from ..domain.state import Side, other_side

# A count nobody has actually claimed. Distinct from 0, which is a claim.
UNCLAIMED = None


class SeriesNotFoundError(Exception):
    """No declaration, or no sub-game logs, for the requested game_id."""


def load_series(logs_dir: Path, game_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Return `(declaration, [log, ...])` ordered by sub-game number."""
    declaration_path = logs_dir / f"declaration_{game_id}.json"
    if not declaration_path.is_file():
        raise SeriesNotFoundError(f"no declaration artifact at {declaration_path}")
    logs = sorted(logs_dir.glob(f"log_{game_id}_g*.json"))
    if not logs:
        raise SeriesNotFoundError(f"no sub-game logs matching log_{game_id}_g*.json in {logs_dir}")
    return (
        json.loads(declaration_path.read_text(encoding="utf-8")),
        [json.loads(p.read_text(encoding="utf-8")) for p in logs],
    )


def _own_github_commit(log: dict[str, Any]) -> str | None:
    """The commit this side actually played, from its sealed step-0 record.

    Book ch.5 makes this mandatory in the step-zero declaration and requires it
    to reach the emailed JSON as `github_commit` (§9). Returns None when the
    record predates us sealing it — NEVER a guess: a fabricated commit hash in
    a league report is precisely the false declaration App. E rules 37/38
    punish, and "the version we happen to be on now" is not the version that
    played.
    """
    for record in log.get("records", []):
        payload = record.get("payload", {})
        if payload.get("step") == 0:
            return payload.get("github_commit")
    return None


def sub_game_rows(
    declaration: dict[str, Any], logs: list[dict[str, Any]], config: GameConfig, *, own_tokens: int
) -> list[dict[str, Any]]:
    """One row per sub-game, keyed by GROUP id rather than role — roles
    alternate, so role is not a stable per-peer key across a series."""
    own_gid = declaration["groups"]["mine"]["group_id"]
    opponent = declaration["groups"]["opponent"]
    opponent_gid = opponent["group_id"]
    game_id = declaration["game_id"]
    rows = []
    for log in logs:
        summary = log["summary"]
        own_role = Side(summary["role"])
        roles = {own_gid: own_role.value, opponent_gid: other_side(own_role).value}
        police, thief = score_for_result(
            summary["result"],
            config.scoring,
            offending_side=Side(summary["offending_side"]) if summary["offending_side"] else None,
        )
        by_role = {"police": police, "thief": thief}
        winner_role = summary.get("winner_role")
        rows.append(
            {
                "sub_game_number": summary["sub_game_number"],
                "roles": roles,
                "started_at": summary["started_at"],
                "ended_at": summary["ended_at"],
                "result": summary["result"],
                "winner_group": next((g for g, r in roles.items() if r == winner_role), None),
                "tie": winner_role is None,
                # OUR key is written LAST in each of these so that it wins a
                # collision. The two ids are only ever equal in self-play,
                # where the report is a degenerate artifact anyway — but there
                # the opponent block is empty, so writing theirs last would
                # silently replace a value we actually know with a null.
                "github_commit": {
                    # Their own declared claim about themselves, carried through
                    # unaltered. Absent stays absent — see UNCLAIMED.
                    opponent_gid: opponent.get("github_commit", UNCLAIMED),
                    own_gid: _own_github_commit(log),
                },
                "tokens": {opponent_gid: opponent.get("tokens_total", UNCLAIMED), own_gid: own_tokens},
                "score": {own_gid: by_role[roles[own_gid]], opponent_gid: by_role[roles[opponent_gid]]},
                "log_files": {own_gid: f"log_{game_id}_g{summary['sub_game_number']:02d}.json"},
                "audit": {
                    "log_verified": summary["audit"]["passed"],
                    "verified_steps": summary["audit"]["verified_steps"],
                    "failed_steps": summary["audit"]["failed_steps"],
                    "tampered": not summary["audit"]["passed"],
                },
            }
        )
    return rows
