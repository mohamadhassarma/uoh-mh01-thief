"""Playing and recording exactly one sub-game of a series: run the match,
exchange the mutual audit reveal, and write that sub-game's `config`/`log`
artifacts (PRD-03). Split out of series.py purely to keep that file under
the project's ~150-line budget.
"""

from __future__ import annotations

import logging
from typing import Any

from ..domain.match import UndefinedOutcomeError
from ..domain.state import other_side
from .artifacts import LogArtifactBuilder, build_config_artifact, write_json
from .mcp_client import send_audit_reveal
from .outcomes import DisputedOutcomeError
from .watchdog import OpponentUnresponsiveError

logger = logging.getLogger(__name__)


async def play_one_sub_game(
    series_runtime, sub_game_number, natural_role, config, peer_config, strategy, game_id, game_uid, my_msg, theirs, out_dir
) -> dict[str, Any]:
    from ..orchestrator import PeerRuntime  # local import: avoid a cycle with orchestrator's own imports

    role = natural_role if sub_game_number % 2 == 1 else other_side(natural_role)
    peer_runtime = PeerRuntime(role, config, peer_config, strategy=strategy, sub_game_number=sub_game_number)
    series_runtime.start_sub_game(sub_game_number, peer_runtime)

    summary: dict[str, Any] = {"sub_game_number": sub_game_number, "role": role.value}
    offending_side_str: str | None = None
    try:
        outcome = await peer_runtime.run_match()
        offending_side_str = outcome.offending_side.value if outcome.offending_side else None
        summary.update(
            terminal_condition=outcome.terminal_condition.value,
            police_score=outcome.police_score,
            thief_score=outcome.thief_score,
            offending_side=offending_side_str,
        )
        result_str, winner_role = outcome.terminal_condition.value, _winner_role(outcome)
    except UndefinedOutcomeError as exc:
        summary["undefined_outcome"] = str(exc)
        result_str, winner_role = "undefined", None
    except DisputedOutcomeError as exc:
        summary["disputed"] = {"mine": exc.mine, "theirs": exc.theirs}
        result_str, winner_role = "disputed", None

    my_reveal = [{"step": r["step"], "nonce": r["nonce"]} for r in peer_runtime.own_sealed_records]
    try:
        audit_of_me = await send_audit_reveal(
            peer_config.opponent_url,
            my_reveal,
            sub_game_number=sub_game_number,
            response_timeout_sec=config.network.response_timeout_sec,
            watchdog_timeout_sec=config.network.watchdog_timeout_sec,
        )
    except OpponentUnresponsiveError:
        # The match outcome is already legitimately decided by this point —
        # an opponent who goes silent specifically during the audit
        # exchange does not get to unwind an already-settled sub-game.
        # Logged as a genuine gap in the audit trail, not silently ignored.
        logger.warning("opponent unresponsive during reveal_audit for sub-game %s", sub_game_number)
        audit_of_me = None
    audit_of_opponent = await series_runtime.wait_for_audit_of_opponent(
        sub_game_number, timeout=config.network.watchdog_timeout_sec
    )
    summary["audit_of_me_by_opponent"] = audit_of_me.passed if audit_of_me else None
    summary["audit_of_opponent_by_me"] = audit_of_opponent.passed if audit_of_opponent else None

    terms = my_msg.terms
    write_json(
        out_dir / f"config_{game_id}_g{sub_game_number:02d}.json",
        build_config_artifact(game_id=game_id, game_uid=game_uid, sub_game_number=sub_game_number, terms=terms),
    )
    log_builder = LogArtifactBuilder(
        game_id=game_id,
        game_uid=game_uid,
        sub_game_number=sub_game_number,
        role=role.value,
        group_id=my_msg.identity["group_id"],
        opponent_group_id=theirs.identity["group_id"],
    )
    for r in peer_runtime.own_sealed_records:
        log_builder.add_record(r["step"], r["payload"], r["nonce"], r["commit"])
    write_json(
        out_dir / f"log_{game_id}_g{sub_game_number:02d}.json",
        log_builder.build(
            result=result_str,
            winner_role=winner_role,
            offending_side=offending_side_str,
            steps=len(peer_runtime.state.move_log),
            audit_of_opponent_passed=audit_of_opponent.passed if audit_of_opponent else None,
            audit_verified_steps=audit_of_opponent.verified_steps if audit_of_opponent else 0,
            audit_failed_steps=list(audit_of_opponent.failed_steps) if audit_of_opponent else [],
        ),
    )
    return summary


def _winner_role(outcome) -> str | None:
    if outcome.police_score == outcome.thief_score:
        return None
    return "police" if outcome.police_score > outcome.thief_score else "thief"
