"""PRD-06: the claim protocol — the ONLY way a capture or a survival is
established once no shared board exists (docs/WIRE.md §5).

Replaces `test_terminal_declaration.py`, which tested the mirrored receiver:
applying the opponent's move to a local copy of the board, recomputing terminal
conditions from that copy, and cross-checking the opponent's action counters.
None of those mechanisms exist any more — the opponent's move is not on the
wire, so there is nothing to apply, recompute against, or count.

What replaces them:

  police MOVE -> capture_claim [r,c]  ->  thief answers claim_response
                                          {"claim": [r,c], "caught": bool}
  thief at its own step budget        ->  win_claim {"type": "survival"}

These call `receive_opponent_move` directly to exercise the receiving side in
isolation.
"""

from __future__ import annotations

from uoh_mh01.domain.board import Position
from uoh_mh01.domain.state import Side
from uoh_mh01.infra.turn_message_builders import build_turn_message
from uoh_mh01.orchestrator import PeerRuntime
from uoh_mh01.shared.peer_config import PeerConfig


def _peer_config(role: str = "police") -> PeerConfig:
    return PeerConfig(
        role=role,
        group_id="test-group",
        group_name="Test Group",
        my_port=8801,
        opponent_url="http://127.0.0.1:8802/mcp",
        turn_timeout_seconds=5,
    )


def _incoming(sender: Side, *, step: int = 1, commit: str | None = None, **fields) -> dict:
    """One inbound TurnMessage, exactly the contract's ten keys."""
    return build_turn_message(
        step=step,
        sender=sender.value,
        hint=fields.pop("hint", "somewhere out there"),
        smell_grid=fields.pop("smell_grid", {}),
        commit=commit or ("a" * 64),
        **fields,
    ).to_wire()


async def test_a_capture_claim_on_my_cell_is_answered_caught_and_flags_me(config_factory):
    config = config_factory(grid_size=5, thief_start=(2, 2), cop_start=(0, 0))
    runtime = PeerRuntime(Side.THIEF, config, _peer_config("thief"))

    # The police claims the exact cell the thief is standing on.
    request = _incoming(Side.POLICE, capture_claim=[2, 2])
    await runtime.receive_opponent_turn(request)

    assert runtime._pending_claim_response == {"claim": [2, 2], "caught": True}
    assert runtime._i_am_caught is True
    # Not settled yet: the honest answer must reach the police first.
    assert runtime.outcome is None


async def test_a_capture_claim_that_misses_is_answered_honestly_and_play_continues(config_factory):
    config = config_factory(grid_size=5, thief_start=(2, 2), cop_start=(0, 0))
    runtime = PeerRuntime(Side.THIEF, config, _peer_config("thief"))

    request = _incoming(Side.POLICE, capture_claim=[4, 4])
    await runtime.receive_opponent_turn(request)

    assert runtime._pending_claim_response == {"claim": [4, 4], "caught": False}
    assert runtime._i_am_caught is False
    assert runtime.outcome is None
    assert runtime.whose_turn is Side.THIEF  # the token came back to me


async def test_a_confirmed_claim_response_settles_the_capture_for_the_police(config_factory):
    config = config_factory(grid_size=5, thief_start=(2, 2), cop_start=(0, 0))
    runtime = PeerRuntime(Side.POLICE, config, _peer_config())

    request = _incoming(Side.THIEF, claim_response={"claim": [2, 2], "caught": True})
    await runtime.receive_opponent_turn(request)

    assert runtime.outcome.terminal_condition.value == "capture_landing"
    assert runtime.outcome.police_score == config.scoring.capture_cop
    assert runtime.outcome.thief_score == config.scoring.capture_thief


async def test_a_denied_claim_response_does_not_settle_anything(config_factory):
    config = config_factory(grid_size=5, thief_start=(2, 2), cop_start=(0, 0))
    runtime = PeerRuntime(Side.POLICE, config, _peer_config())

    await runtime.receive_opponent_turn(_incoming(Side.THIEF, claim_response={"claim": [4, 4], "caught": False}))

    assert runtime.outcome is None


async def test_a_win_claim_settles_survival(config_factory):
    config = config_factory(grid_size=5, thief_start=(2, 2), cop_start=(0, 0))
    runtime = PeerRuntime(Side.POLICE, config, _peer_config())

    await runtime.receive_opponent_turn(_incoming(Side.THIEF, win_claim={"type": "survival"}))

    assert runtime.outcome.terminal_condition.value == "survival"
    assert runtime.outcome.police_score == config.scoring.survival_cop
    assert runtime.outcome.thief_score == config.scoring.survival_thief


async def test_a_declared_barrier_is_noted_on_my_own_board(config_factory):
    config = config_factory(grid_size=5, thief_start=(2, 2), cop_start=(0, 0))
    runtime = PeerRuntime(Side.THIEF, config, _peer_config("thief"))

    await runtime.receive_opponent_turn(
        _incoming(Side.POLICE, commit="b" * 64, barrier_placed=[1, 1])
    )

    # Public by rule, impassable for both — the one board fact that legitimately
    # crosses the wire.
    assert Position(1, 1) in runtime.state.board.barriers


async def test_an_incoming_turn_updates_belief_and_records_the_commit(config_factory):
    config = config_factory(grid_size=5, thief_start=(2, 2), cop_start=(0, 0))
    runtime = PeerRuntime(Side.THIEF, config, _peer_config("thief"))
    before = dict(runtime._belief)

    await runtime.receive_opponent_turn(
        _incoming(Side.POLICE, step=3, smell_grid={"0,0": 0.9}, hint="I am near the northwest.")
    )

    assert runtime._belief != before  # hint + smell folded in
    assert runtime.received_commits.by_step[3] == "a" * 64  # kept for the audit
    # And nothing anywhere holds the opponent's true position.
    assert not hasattr(runtime.state, "cop_pos")


async def test_a_duplicate_turn_is_dropped_not_reapplied(config_factory):
    """At-least-once delivery (kit SPEC §7.1): a retried push repeats the same
    commit. Processing it twice would double-count a step and desync the audit.
    The old response-replay cache is gone — with ack-only tools there is no
    response to replay, so the duplicate is dropped at PROCESSING time."""
    config = config_factory(grid_size=5, thief_start=(2, 2), cop_start=(0, 0))
    runtime = PeerRuntime(Side.THIEF, config, _peer_config("thief"))

    turn = _incoming(Side.POLICE, step=1, barrier_placed=[1, 1])
    await runtime.receive_opponent_turn(turn)
    await runtime.receive_opponent_turn(turn)  # the retry

    assert len(runtime.received_commits.by_step) == 1
    assert Position(1, 1) in runtime.state.board.barriers


async def test_a_turn_claiming_my_own_role_is_refused(config_factory):
    config = config_factory(grid_size=5, thief_start=(2, 2), cop_start=(0, 0))
    runtime = PeerRuntime(Side.THIEF, config, _peer_config("thief"))

    await runtime.receive_opponent_turn(_incoming(Side.THIEF))

    assert runtime.outcome.terminal_condition.value == "technical_loss"
    assert runtime.outcome.offending_side is Side.POLICE


async def test_a_malformed_turn_is_refused_before_any_state_change(config_factory):
    config = config_factory(grid_size=5, thief_start=(2, 2), cop_start=(0, 0))
    runtime = PeerRuntime(Side.THIEF, config, _peer_config("thief"))
    before = dict(runtime._belief)

    bad = _incoming(Side.POLICE)
    bad["commit"] = "NOT-HEX"
    await runtime.receive_opponent_turn(bad)

    assert runtime.outcome.terminal_condition.value == "technical_loss"
    assert runtime._belief == before  # validation happens BEFORE absorption
    assert runtime.received_commits.by_step == {}
