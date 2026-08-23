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

IT IS ALSO THE DUPLICATE-SEND INTERLOCK. Book §9.3 requires each agent to mail
its own report with no human in the loop, and names the danger in the same
breath: automation is "ברכה ומלכודת כאחת" — a blessing and a trap — because a
loop with a bug holds the keys to a live mail account. A row is written here
BEFORE the send is attempted and updated after, so a second attempt on the
same `game_uid` can see that one is already in flight or done and refuse.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

LEDGER_PATH = Path("league") / "counted_games.json"

# A row's lifecycle. `SENDING` is written before the Gmail call and is what
# makes a duplicate automatic send impossible even if the process is killed
# between the two writes.
STATUS_SENDING = "sending"
STATUS_SENT = "sent"
STATUS_FAILED = "failed"


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"schema_version": "1.0", "counted_series": []}
    return json.loads(path.read_text(encoding="utf-8"))


def is_first_meeting(opponent_group_id: str, *, path: Path = LEDGER_PATH) -> bool:
    """True only if no counted series against this group has been recorded."""
    return not any(row["opponent_group_id"] == opponent_group_id for row in _load(path)["counted_series"])


def already_reported(game_uid: str, *, path: Path = LEDGER_PATH) -> bool:
    """True once a send for this series has SUCCEEDED. A row left at
    `sending` (the process died mid-send) or `failed` is not a success, so the
    manual fallback can still retry it — but see `find`, which is what blocks a
    second automatic attempt."""
    row = find(game_uid, path=path)
    return bool(row and row.get("status") == STATUS_SENT)


def find(game_uid: str, *, path: Path = LEDGER_PATH) -> dict[str, Any] | None:
    return next((row for row in _load(path)["counted_series"] if row["game_uid"] == game_uid), None)


def counted_games_played(*, path: Path = LEDGER_PATH) -> int:
    """How many counted series this group has played — the honest answer to
    the book's Game-Count Declaration (ch.9.2.1). Our own count only: the
    opponent's is their unverifiable claim about themselves, and inventing a
    number for them is exactly what `UNCLAIMED` exists to avoid."""
    return len(_load(path)["counted_series"])


def record_counted_series(
    *,
    opponent_group_id: str,
    game_id: str,
    game_uid: str,
    ended_at: str,
    status: str = STATUS_SENT,
    detail: str | None = None,
    path: Path = LEDGER_PATH,
) -> dict[str, Any]:
    """Insert or UPDATE this series' row and persist.

    Keyed on `game_uid`, so re-running the pipeline can never inflate the
    count — it only ever moves an existing row's `status` along
    (`sending` -> `sent` / `failed`).
    """
    ledger = _load(path)
    row = next((r for r in ledger["counted_series"] if r["game_uid"] == game_uid), None)
    if row is None:
        row = {"opponent_group_id": opponent_group_id, "game_id": game_id, "game_uid": game_uid}
        ledger["counted_series"].append(row)
    row.update(ended_at=ended_at, status=status)
    if detail is not None:
        row["detail"] = detail
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ledger, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return ledger
