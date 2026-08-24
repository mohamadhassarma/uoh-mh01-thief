"""The three standardized JSON artifacts this stage owns (PRD-03 / book
App. F Table 20, filenames verified directly against the book PDF and
cross-checked against the reference's docs/sample-run/): `declaration`
(once per series), `config` and `log` (once per sub-game). `result` is
PRD-07's, once a series' worth of these exists to aggregate.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..domain.canonical import canonical_json
from ..domain.scoring import check_result_vocabulary


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _links(game_id: str) -> dict[str, str]:
    return {
        "declaration": f"declaration_{game_id}.json",
        "config": f"config_{game_id}_g<NN>.json",
        "log": f"log_{game_id}_g<NN>.json",
        "result": f"result_{game_id}.json",
    }


def build_declaration(
    *, game_id: str, game_uid: str, num_sub_games: int, groups: dict[str, dict[str, Any]], started_at: str, ended_at: str
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "declaration_type": "pre_game_declaration",
        "game_id": game_id,
        "game_uid": game_uid,
        "links": _links(game_id),
        "num_sub_games": num_sub_games,
        "groups": groups,
        "game_started_at": started_at,
        "game_ended_at": ended_at,
    }


def build_config_artifact(*, game_id: str, game_uid: str, sub_game_number: int, terms: dict[str, Any]) -> dict[str, Any]:
    config_name = f"config_{game_id}_g{sub_game_number:02d}.json"
    body_without_hash = {
        "schema_version": "1.0",
        "game_id": game_id,
        "game_uid": game_uid,
        "sub_game_number": sub_game_number,
        "links": _links(game_id),
        "terms": terms,
        "config_name": config_name,
    }
    config_sha256 = hashlib.sha256(canonical_json(body_without_hash).encode("utf-8")).hexdigest()
    return {**body_without_hash, "config_sha256": config_sha256}


@dataclass
class LogArtifactBuilder:
    game_id: str
    game_uid: str
    sub_game_number: int
    role: str
    group_id: str
    opponent_group_id: str
    # REQUIRED, and deliberately not a `default_factory=now_iso`. The builder is
    # constructed at the END of a sub-game - after the match and after the audit
    # exchange - so a default would stamp `started_at` within microseconds of
    # `ended_at` and quietly report every sub-game as instantaneous. That is
    # exactly what it did. The caller has to say when the sub-game began.
    started_at: str
    records: list[dict[str, Any]] = field(default_factory=list)
    # The OPPONENT's revealed chain, kept rather than discarded after the
    # audit. Their sealed step-0 is the only place their per-sub-game
    # `github_commit` exists (rule 53); verifying it in memory and throwing
    # it away left that field unreachable at report-build time. Key name
    # matches the interop kit's own artifacts
    # (examples/pairing-artifacts/log_*.json, schema 1.1).
    opponent_records: list[dict[str, Any]] = field(default_factory=list)

    def add_record(self, step: int, payload: dict[str, Any], nonce: str, commit: str) -> None:
        self.records.append({"payload": payload, "nonce": nonce, "commit": commit, "step": step})

    def build(
        self,
        *,
        result: str | None,
        winner_role: str | None,
        offending_side: str | None,
        steps: int,
        audit_of_opponent_passed: bool | None,
        audit_verified_steps: int,
        audit_failed_steps: list[int],
        audit_reason: str | None = None,
    ) -> dict[str, Any]:
        check_result_vocabulary(result or "", "the log artifact (summary.result)")
        ended_at = now_iso()
        return {
            # 1.1 adds `opponent_records`, matching the kit's own log schema.
            "schema_version": "1.1",
            "game_id": self.game_id,
            "game_uid": self.game_uid,
            "links": _links(self.game_id),
            "summary": {
                "sub_game_number": self.sub_game_number,
                "group_id": self.group_id,
                "role": self.role,
                "opponent_group_id": self.opponent_group_id,
                "result": result,
                "winner_role": winner_role,
                # Who was blamed for a technical loss — see PRD-03
                # "Symmetric timeout outcomes": both sides' own artifacts
                # must agree on this, not just on `result`.
                "offending_side": offending_side,
                "steps": steps,
                "started_at": self.started_at,
                "ended_at": ended_at,
                "audit": {
                    "passed": audit_of_opponent_passed,
                    "verified_steps": audit_verified_steps,
                    "failed_steps": audit_failed_steps,
                    # Only set on a failure — including the verdict-floor
                    # failures (nothing verified / not every step
                    # explained), which would otherwise be invisible.
                    "reason": audit_reason,
                },
            },
            "records": self.records,
            "opponent_records": self.opponent_records,
        }


def write_json(path: str | Path, body: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body, indent=2, ensure_ascii=False), encoding="utf-8")
