"""The counted-games ledger: which opponents this group has already played a
COUNTED series against.

COMMITTED TO THE REPO, not gitignored and not held in memory. Two reasons, both
from PRD-07:

  * A grader re-cloning the repo must be able to see that a pairing was a
    repeat. An uncommitted ledger cannot prove anything to anyone.
  * A ledger that never advances makes the NEXT counted series against the
    same opponent declare `first_meeting_between_groups: true` a second time.
    That is a rules-37/38 false declaration produced entirely by accident, and
    App. E rule 35 charges both teams for a contradictory report — so the bug
    would take an innocent opponent down too.

Only the FIRST meeting between two groups counts (App. E rule 52); warm-ups
are permitted, recommended, and owe no report to anyone, so they must never
reach this file either.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

LEDGER_PATH = Path("league") / "counted_games.json"


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"schema_version": "1.0", "counted_series": []}
    return json.loads(path.read_text(encoding="utf-8"))


def is_first_meeting(opponent_group_id: str, *, path: Path = LEDGER_PATH) -> bool:
    """True only if no counted series against this group has been recorded."""
    return not any(row["opponent_group_id"] == opponent_group_id for row in _load(path)["counted_series"])


def counted_games_played(*, path: Path = LEDGER_PATH) -> int:
    """How many counted series this group has played — the honest answer to
    the book's Game-Count Declaration (ch.9.2.1). Our own count only: the
    opponent's is their unverifiable claim about themselves, and inventing a
    number for them is exactly what `UNCLAIMED` exists to avoid."""
    return len(_load(path)["counted_series"])


def record_counted_series(
    *, opponent_group_id: str, game_id: str, game_uid: str, ended_at: str, path: Path = LEDGER_PATH
) -> dict[str, Any]:
    """Append this series and persist. Idempotent on `game_uid`, so a re-run of
    the report pipeline cannot inflate the count."""
    ledger = _load(path)
    if any(row["game_uid"] == game_uid for row in ledger["counted_series"]):
        return ledger
    ledger["counted_series"].append(
        {
            "opponent_group_id": opponent_group_id,
            "game_id": game_id,
            "game_uid": game_uid,
            "ended_at": ended_at,
        }
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ledger, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return ledger
