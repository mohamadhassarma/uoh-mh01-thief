import pytest

from uoh_mh01.domain.board import Direction, Position
from uoh_mh01.domain.match import BarrierAction, MoveAction
from uoh_mh01.domain.state import Side
from uoh_mh01.infra.protocol import (
    MoveRequest,
    ProtocolError,
    action_to_request,
    declare_terminal_request,
    parse_move_request,
    request_to_action,
)
from uoh_mh01.infra.protocol_response import MoveResponse, TerminalInfo


def test_move_action_round_trips_through_the_wire_shape():
    action = MoveAction(Direction.N)
    request = action_to_request(action, Side.POLICE, 3, police_actions_taken=1, thief_actions_taken=0)
    assert request.role == "police"
    assert request.action_type == "move"
    assert request.direction == "N"
    assert request.police_actions_taken == 1
    assert request_to_action(request) == action


def test_barrier_action_round_trips_through_the_wire_shape():
    action = BarrierAction(Position(2, 3))
    request = action_to_request(action, Side.POLICE, 5, police_actions_taken=2, thief_actions_taken=1)
    assert request.action_type == "barrier"
    assert request.target_row == 2
    assert request.target_col == 3
    assert request_to_action(request) == action


def test_action_to_request_carries_a_claimed_condition_when_given():
    action = MoveAction(Direction.N)
    request = action_to_request(
        action, Side.POLICE, 3, police_actions_taken=1, thief_actions_taken=0, claimed_condition="capture_landing"
    )
    assert request.claimed_condition == "capture_landing"


def test_declare_terminal_request_carries_no_move():
    request = declare_terminal_request(
        Side.THIEF, 4, "capture_entrapment", police_actions_taken=2, thief_actions_taken=2
    )
    assert request.action_type == "declare_terminal"
    assert request.direction is None
    assert request.target_row is None
    assert request.claimed_condition == "capture_entrapment"


def test_parse_move_request_accepts_valid_move():
    request = parse_move_request("thief", 1, "move", "STAY", None, None)
    assert request == MoveRequest(role="thief", turn_number=1, action_type="move", direction="STAY")


def test_parse_move_request_accepts_valid_barrier():
    request = parse_move_request("police", 1, "barrier", None, 2, 3)
    assert request == MoveRequest(role="police", turn_number=1, action_type="barrier", target_row=2, target_col=3)


def test_parse_move_request_accepts_valid_declare_terminal():
    request = parse_move_request(
        "thief", 1, "declare_terminal", None, None, None, claimed_condition="undefined_ceiling"
    )
    assert request.action_type == "declare_terminal"
    assert request.claimed_condition == "undefined_ceiling"


def test_parse_move_request_rejects_bad_role():
    with pytest.raises(ProtocolError, match="role"):
        parse_move_request("wizard", 1, "move", "N", None, None)


def test_parse_move_request_rejects_bad_action_type():
    with pytest.raises(ProtocolError, match="action_type"):
        parse_move_request("police", 1, "teleport", None, None, None)


def test_parse_move_request_move_without_direction_rejected():
    with pytest.raises(ProtocolError, match="direction"):
        parse_move_request("police", 1, "move", None, None, None)


def test_parse_move_request_barrier_without_target_rejected():
    with pytest.raises(ProtocolError, match="target"):
        parse_move_request("police", 1, "barrier", None, None, None)


def test_parse_move_request_declare_terminal_without_claim_rejected():
    with pytest.raises(ProtocolError, match="claimed_condition"):
        parse_move_request("police", 1, "declare_terminal", None, None, None)


def test_move_response_round_trips_through_dict():
    response = MoveResponse(accepted=True, terminal=TerminalInfo("survival", 5, 10, None), claim_agreement=True)
    d = response.to_dict()
    restored = MoveResponse.from_dict(d)
    assert restored == response


def test_move_response_without_terminal_round_trips():
    response = MoveResponse(accepted=False, reason="not your turn")
    restored = MoveResponse.from_dict(response.to_dict())
    assert restored == response


def test_move_response_divergence_round_trips():
    response = MoveResponse(accepted=False, divergence="counter mismatch: ...")
    restored = MoveResponse.from_dict(response.to_dict())
    assert restored == response
