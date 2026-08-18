"""B1/B2 (PRD-02 'Stage 2 corrections'): terminal conditions must be
DECLARED and independently re-verified rather than trusted, and every
message's action counters must match the receiver's own local expectations
or be rejected as a divergence. These tests call `receive_opponent_move`
directly to exercise the passive/receiving side in isolation.
"""

import dataclasses

from uoh_mh01.domain.board import Direction, Position
from uoh_mh01.domain.match import MoveAction
from uoh_mh01.domain.state import Side
from uoh_mh01.infra.protocol_builders import action_to_request, declare_terminal_request
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


async def test_receive_declare_terminal_entrapment_confirmed_scores_capture_not_technical_loss(config_factory):
    config = config_factory(grid_size=5, thief_start=(0, 0), cop_start=(4, 4))
    runtime = PeerRuntime(Side.POLICE, config, _peer_config())
    boxed = runtime.state.board.with_barrier(Position(0, 1)).with_barrier(Position(1, 0))
    runtime.state = dataclasses.replace(runtime.state, board=boxed)

    request = declare_terminal_request(
        Side.THIEF, runtime.state.turn_number, "capture_entrapment", police_actions_taken=0, thief_actions_taken=0
    )
    response = await runtime.receive_opponent_move(request)

    assert response.accepted is True
    assert response.claim_agreement is True
    assert runtime.outcome.terminal_condition.value == "capture_entrapment"
    assert runtime.outcome.police_score == config.scoring.capture_cop
    assert runtime.outcome.thief_score == config.scoring.capture_thief


async def test_receive_declare_terminal_disagreement_stages_a_pending_dispute_not_a_silent_finish(config_factory):
    config = config_factory(grid_size=5, thief_start=(0, 0), cop_start=(4, 4))
    runtime = PeerRuntime(Side.POLICE, config, _peer_config())
    # The thief is NOT actually trapped under my own mirrored state, so my
    # independent recomputation disagrees with the claim.

    request = declare_terminal_request(
        Side.THIEF, runtime.state.turn_number, "capture_entrapment", police_actions_taken=0, thief_actions_taken=0
    )
    response = await runtime.receive_opponent_move(request)

    assert response.claim_agreement is False
    assert runtime.outcome is None  # never silently resolved in either side's favour
    assert runtime._pending_error is not None
    assert runtime._pending_error.mine is None
    assert runtime._pending_error.theirs == "capture_entrapment"


async def test_receive_declare_terminal_ceiling_confirmed_stages_undefined_outcome(config_factory):
    config = config_factory(max_moves=2)
    runtime = PeerRuntime(Side.POLICE, config, _peer_config())
    runtime.state = dataclasses.replace(runtime.state, whose_turn=Side.THIEF, thief_actions_taken=2)

    request = declare_terminal_request(
        Side.THIEF, runtime.state.turn_number, "undefined_ceiling", police_actions_taken=0, thief_actions_taken=2
    )
    response = await runtime.receive_opponent_move(request)

    assert response.accepted is True
    assert response.claim_agreement is True
    assert runtime.outcome is None  # not scored — the rulebook does not define this case
    assert runtime._pending_error is not None


async def test_receive_move_with_wrong_counters_is_rejected_without_mutating_state(config_factory):
    config = config_factory(grid_size=5, thief_start=(2, 2))
    runtime = PeerRuntime(Side.POLICE, config, _peer_config())
    runtime.state = dataclasses.replace(runtime.state, whose_turn=Side.THIEF)
    original_state = runtime.state

    request = action_to_request(
        MoveAction(Direction.W),
        Side.THIEF,
        runtime.state.turn_number,
        police_actions_taken=0,
        thief_actions_taken=99,  # wrong: should be 1 after this move
    )
    response = await runtime.receive_opponent_move(request)

    assert response.accepted is False
    assert response.divergence is not None
    assert runtime.state is original_state


async def test_receive_ordinary_move_with_no_claim_and_no_conflict_just_continues(config_factory):
    config = config_factory(grid_size=5, thief_start=(2, 2))
    runtime = PeerRuntime(Side.POLICE, config, _peer_config())
    runtime.state = dataclasses.replace(runtime.state, whose_turn=Side.THIEF)

    request = action_to_request(
        MoveAction(Direction.W), Side.THIEF, runtime.state.turn_number, police_actions_taken=0, thief_actions_taken=1
    )
    response = await runtime.receive_opponent_move(request)

    assert response.accepted is True
    assert response.claim_agreement is None  # no claim was made — nothing to agree or disagree with
    assert runtime.outcome is None
    assert runtime.state.whose_turn is Side.POLICE  # turn advanced normally
