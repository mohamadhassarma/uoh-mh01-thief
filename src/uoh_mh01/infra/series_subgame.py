"""Playing and recording exactly one sub-game of a series: run the match,
exchange the mutual audit reveal, and write that sub-game's `config`/`log`
artifacts (PRD-03). Split out of series.py purely to keep that file under
the project's ~150-line budget.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ..domain.brain_base import resolve_strategy
from ..domain.match import UndefinedOutcomeError
from ..domain.sealed_payload import build_audit_payload
from ..domain.state import Side
from ..gui.live_state import LIVE_STATE_NAME, LiveStatePublisher
from .artifacts import LogArtifactBuilder, build_config_artifact, now_iso, write_json
from .audit import verify_revealed
from .mcp_client import send_audit_reveal
from .outcomes import DisputedOutcomeError

logger = logging.getLogger(__name__)


async def play_one_sub_game(
    series_runtime,
    sub_game_number,
    role,
    config,
    peer_config,
    strategy,
    seed,
    series,
    my_msg,
    theirs,
    out_dir,
    repo_commit=None,
) -> dict[str, Any]:
    """`role` and the per-sub-game greetings `my_msg`/`theirs` are decided by
    the caller, because the handshake now runs per sub-game and has to know the
    role BEFORE this is called (infra/series_handshake.py). `series` carries
    the pinned series identity — game_id/game_uid/terms — which never varies."""
    from ..orchestrator import PeerRuntime  # local import: avoid a cycle with orchestrator's own imports

    game_id, game_uid = series.game_id, series.game_uid
    # The sub-game's clock starts HERE, not where the log builder happens to be
    # constructed - that is at the far end of this function, after the match and
    # the audit exchange, and stamping there made every sub-game look
    # instantaneous. Deliberately after this sub-game's handshake, which the
    # caller has already done: the handshake is a rendezvous that can sit
    # waiting for the opponent's process to appear, and folding that wait into
    # the sub-game's duration would measure their punctuality, not the game.
    started_at = now_iso()
    this_sub_game_strategy = strategy or _strategy_for_sub_game(peer_config, role, seed, sub_game_number)
    peer_runtime = PeerRuntime(
        role,
        config,
        peer_config,
        strategy=this_sub_game_strategy,
        sub_game_number=sub_game_number,
        repo_commit=repo_commit,
        live_publisher=LiveStatePublisher(
            Path(out_dir) / LIVE_STATE_NAME, game_id=game_id, game_uid=game_uid
        ),
    )
    series_runtime.start_sub_game(sub_game_number, peer_runtime)
    # Rule #53: the host-spec declaration is sealed BEFORE the first move, so
    # it is inside the chain the opponent audits rather than appended after the
    # fact. Never sent as a turn — see _SealingMixin.seal_step_zero.
    peer_runtime.seal_step_zero()

    # `game_id`/`game_uid` ride on every summary so the peer process can build
    # and mail its own report at series end (book §9.3) without re-reading the
    # declaration off disk to find out which series it just played.
    summary: dict[str, Any] = {
        "sub_game_number": sub_game_number,
        "role": role.value,
        "game_id": game_id,
        "game_uid": game_uid,
    }
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

    # The FULL sealed chain, not just nonces: the opponent has no mirrored
    # copy of my moves to re-hash against any more, so the payload must
    # travel with the reveal (docs/WIRE.md §5).
    my_reveal = build_audit_payload(
        sender=role.value,
        records=[
            {"payload": r["payload"], "nonce": r["nonce"], "commit": r["commit"]}
            for r in peer_runtime.own_sealed_records
        ],
        result_claim=result_str,
    )
    # Push mine (best-effort — the opponent may already be exiting), then poll
    # my own inbox for theirs and verify it MYSELF. `submit_audit` acks like
    # every other tool, so there is no verdict to receive: each side computes
    # its own verdict on the other's chain (docs/WIRE.md §5).
    await send_audit_reveal(
        peer_config.opponent_url,
        my_reveal,
        sub_game_number=sub_game_number,
        response_timeout_sec=config.network.response_timeout_sec,
        watchdog_timeout_sec=config.network.watchdog_timeout_sec,
    )
    their_payload = await series_runtime.wait_for_audit_reveal(
        sub_game_number=sub_game_number, timeout=config.network.watchdog_timeout_sec
    )
    audit_of_opponent = None
    if their_payload is None:
        logger.warning("opponent never revealed its chain for sub-game %s", sub_game_number)
    else:
        audit_of_opponent = verify_revealed(their_payload.get("records", []), peer_runtime.received_commits)
    # `audit_of_me_by_opponent` is deliberately absent: under an ack-only wire
    # the opponent's verdict on ME never crosses back, and inventing a value
    # for it would be a guess recorded as evidence.
    summary["audit_of_opponent_by_me"] = audit_of_opponent.passed if audit_of_opponent else None

    terms = series.terms
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
        started_at=started_at,
    )
    for r in peer_runtime.own_sealed_records:
        log_builder.add_record(r["step"], r["payload"], r["nonce"], r["commit"])
    write_json(
        out_dir / f"log_{game_id}_g{sub_game_number:02d}.json",
        log_builder.build(
            result=result_str,
            winner_role=winner_role,
            offending_side=offending_side_str,
            steps=peer_runtime.state.step_number,
            audit_of_opponent_passed=audit_of_opponent.passed if audit_of_opponent else None,
            audit_verified_steps=audit_of_opponent.verified_steps if audit_of_opponent else 0,
            audit_failed_steps=list(audit_of_opponent.failed_steps) if audit_of_opponent else [],
            audit_reason=(
                audit_of_opponent.reason
                if audit_of_opponent
                else 'the opponent never revealed its chain'
            ),
        ),
    )
    return summary


def _strategy_for_sub_game(peer_config, role, seed, sub_game_number):
    """Resolves a FRESH, role-correct brain for THIS sub-game, never reused
    across a role-alternating series (called only when the caller did not
    pass an explicit fixed `strategy` — e.g. the stalling-peer test runner,
    which deliberately wants one strategy for every sub-game regardless of
    role). A single strategy resolved once, at series start, from the
    process's natural role would silently run the wrong brain (or carry
    stale cross-sub-game state, e.g. a thief's direction streak) on every
    role-swapped sub-game — PRD-05's `[strategy] police_class`/`thief_class`
    are two DIFFERENT classes precisely because this process plays police in
    some sub-games and thief in others."""
    dotted_path = peer_config.police_class if role is Side.POLICE else peer_config.thief_class
    sub_game_seed = seed if seed is None else f"{seed}-{sub_game_number}"
    return resolve_strategy(dotted_path, sub_game_seed)


def _winner_role(outcome) -> str | None:
    if outcome.police_score == outcome.thief_score:
        return None
    return "police" if outcome.police_score > outcome.thief_score else "thief"
