"""Re-verify a series' sealed chains from the JSON artifacts on disk (book
ch.7's mandatory replay requirement).

WHAT THIS CAN AND CANNOT PROVE. During play, `infra/audit.py` checks a
revealed record against **the commit that actually arrived live**, because a
revealer could rewrite the `commit` field inside its own reveal after the
fact. A replay from disk has no live channel to compare against: all it holds
is the artifact. So what it proves is narrower and worth stating plainly — the
artifact is INTERNALLY CONSISTENT: every sealed record still re-hashes to the
commit stored beside it, so the file has not been edited since it was written.
That is exactly the tamper-evidence ch.7 asks a replay to demonstrate, and it
is not the same claim as "the opponent played honestly", which only the live
audit recorded in the log can support.

THE HASHING IS NOT REIMPLEMENTED HERE. `verify_revealed` is called with a
`ReceivedCommitLog` built from the artifact's own stored commits, so the
comparison, the step-0 rule and the verdict floor all come from the one module
that already gets them right. A second SHA-256 implementation that agreed with
the first would prove nothing about the first; one that disagreed would be a
bug in the viewer, reported as tampering in someone's real series.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..infra.audit import STEP_ZERO, AuditResult, ReceivedCommitLog, verify_revealed
from ..report.series_reader import load_series

VERDICT_OK = "Verified OK"
VERDICT_TAMPERED = "TAMPERED"


@dataclass(frozen=True)
class SubGameVerdict:
    sub_game_number: int
    role: str
    group_id: str
    records: int
    step_zero_present: bool
    audit: AuditResult
    result: str | None = None

    @property
    def ok(self) -> bool:
        return self.audit.passed

    @property
    def verdict(self) -> str:
        return VERDICT_OK if self.ok else VERDICT_TAMPERED


@dataclass(frozen=True)
class SeriesVerdict:
    game_id: str
    game_uid: str
    sub_games: tuple[SubGameVerdict, ...]

    @property
    def ok(self) -> bool:
        # An empty series is NOT ok: "nothing to check" must never render as a
        # pass, for the same reason an empty reveal cannot (infra/audit.py's
        # verdict floor).
        return bool(self.sub_games) and all(sub.ok for sub in self.sub_games)

    @property
    def verdict(self) -> str:
        return VERDICT_OK if self.ok else VERDICT_TAMPERED

    @property
    def verified_steps(self) -> int:
        return sum(sub.audit.verified_steps for sub in self.sub_games)


def _step_of(record: dict[str, Any]) -> int:
    payload = record.get("payload")
    if isinstance(payload, dict) and "step" in payload:
        return int(payload["step"])
    return int(record.get("step", -1))


def commits_as_received(records: list[dict[str, Any]]) -> ReceivedCommitLog:
    """The artifact's own stored commits, keyed by step, as the thing to
    re-hash against.

    STEP 0 IS DELIBERATELY EXCLUDED. It is disclosure-only: never transmitted
    as a turn, so it has no live counterpart and is not one of the steps the
    match played. `verify_revealed` already checks it for self-consistency and
    already leaves it out of `verified_steps`; putting it in here as well would
    make the played-steps floor expect one more step than was ever played, and
    every honest series would replay as TAMPERED.
    """
    log = ReceivedCommitLog()
    for record in records:
        step = _step_of(record)
        commit = record.get("commit")
        if step != STEP_ZERO and isinstance(commit, str):
            log.record(step, commit)
    return log


def verify_sub_game(log: dict[str, Any]) -> SubGameVerdict:
    records = log.get("records", [])
    summary = log.get("summary", {})
    return SubGameVerdict(
        sub_game_number=summary.get("sub_game_number", 0),
        role=summary.get("role", "?"),
        group_id=summary.get("group_id", "?"),
        records=len(records),
        step_zero_present=any(_step_of(r) == STEP_ZERO for r in records),
        audit=verify_revealed(records, commits_as_received(records)),
        result=summary.get("result"),
    )


def verify_series(logs_dir: Path, game_id: str) -> SeriesVerdict:
    declaration, logs = load_series(logs_dir, game_id)
    return SeriesVerdict(
        game_id=declaration.get("game_id", game_id),
        game_uid=declaration.get("game_uid", "?"),
        sub_games=tuple(verify_sub_game(log) for log in logs),
    )
