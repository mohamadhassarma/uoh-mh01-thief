import dataclasses

import pytest

from uoh_mh01.domain.board import Direction, Position
from uoh_mh01.domain.reducers import apply_barrier, apply_move
from uoh_mh01.domain.rules import is_move_legal
from uoh_mh01.domain.state import ActionType, IllegalActionError, MatchState, Side, next_turn


def test_apply_move_updates_police_position(config):
    state = MatchState.initial(config, first_mover=Side.POLICE)
    new_state = apply_move(state, Direction.E)
    assert new_state.cop_pos == Position(0, 1)
    assert new_state.thief_pos == state.thief_pos
    assert new_state.police_actions_taken == 1
    assert new_state.thief_actions_taken == 0
    assert len(new_state.move_log) == 1
    assert new_state.move_log[0].actor is Side.POLICE
    assert new_state.move_log[0].action_type is ActionType.MOVE


def test_apply_move_updates_thief_position(config):
    state = MatchState.initial(config, first_mover=Side.THIEF)
    new_state = apply_move(state, Direction.W)
    assert new_state.thief_pos == Position(config.board.thief_start[0], config.board.thief_start[1] - 1)
    assert new_state.cop_pos == state.cop_pos


def test_apply_move_raises_on_off_board(config):
    state = MatchState.initial(config, first_mover=Side.POLICE)  # cop at (0,0)
    with pytest.raises(IllegalActionError) as excinfo:
        apply_move(state, Direction.N)
    assert excinfo.value.offending_side is Side.POLICE


def test_apply_move_raises_on_barrier(config_factory):
    config = config_factory(cop_start=(2, 2))
    state = MatchState.initial(config, first_mover=Side.POLICE)
    state = dataclasses.replace(state, board=state.board.with_barrier(Position(2, 3)))
    with pytest.raises(IllegalActionError):
        apply_move(state, Direction.E)


def test_barrier_placement_is_irreversible(config):
    state = MatchState.initial(config, first_mover=Side.POLICE)
    target = Position(0, 1)
    state = apply_barrier(state, target)
    assert target in state.board.barriers
    # advance through several further actions; barrier must never disappear
    state = next_turn(state, Side.POLICE)
    state = apply_move(state, Direction.STAY)  # thief's turn
    state = next_turn(state, Side.POLICE)
    state = apply_move(state, Direction.S)  # police moves elsewhere
    assert target in state.board.barriers
    assert len(state.board.barriers) == 1  # nothing removed it


def test_barrier_quota_enforced_via_apply(config_factory):
    config = config_factory(max_barriers=1)
    state = MatchState.initial(config, first_mover=Side.POLICE)
    state = apply_barrier(state, Position(0, 1))
    assert state.barriers_placed == 1
    with pytest.raises(IllegalActionError):
        apply_barrier(state, Position(1, 0))


def test_barrier_quota_is_exact(config_factory):
    # Placement number max_barriers must succeed; placement number
    # max_barriers + 1 must be rejected — not one before, not one after.
    max_barriers = 3
    config = config_factory(max_barriers=max_barriers, cop_start=(2, 2))
    state = MatchState.initial(config, first_mover=Side.POLICE)
    targets = [Position(1, 2), Position(3, 2), Position(2, 1), Position(2, 3)]  # 4 candidates, cop's own neighbours

    for target in targets[:max_barriers]:
        state = apply_barrier(state, target)  # must not raise

    assert state.barriers_placed == max_barriers

    with pytest.raises(IllegalActionError):
        apply_barrier(state, targets[max_barriers])  # the (max_barriers + 1)-th placement


def test_only_police_may_place_barriers(config):
    state = MatchState.initial(config, first_mover=Side.THIEF)
    with pytest.raises(IllegalActionError):
        apply_barrier(state, state.thief_pos)


def test_capture_by_police_landing_on_thief(config_factory):
    config = config_factory(cop_start=(2, 1), thief_start=(2, 2))
    state = MatchState.initial(config, first_mover=Side.POLICE)
    state = apply_move(state, Direction.E)
    assert state.cop_pos == state.thief_pos == Position(2, 2)
    entry = state.move_log[-1]
    assert entry.capture_triggered
    assert entry.capture_claimed_by_police


def test_thief_walking_onto_police_is_an_ordinary_move_not_a_capture(config_factory):
    # PRD-03 (verified against the book's Table 2 + rules #21/#22, supersedes
    # PRD-01's original symmetric reading): capture-by-landing is
    # police-turn-gated. The thief walking onto the police's cell is an
    # ORDINARY move — both agents end up legally co-located, and the match
    # continues; it is NOT a capture just because the thief caused the
    # overlap.
    config = config_factory(cop_start=(2, 2), thief_start=(2, 3))
    state = MatchState.initial(config, first_mover=Side.THIEF)
    state = apply_move(state, Direction.W)
    assert state.thief_pos == state.cop_pos == Position(2, 2)
    entry = state.move_log[-1]
    assert not entry.capture_triggered
    assert not entry.capture_claimed_by_police


def test_police_may_claim_a_thief_caused_co_location_on_its_own_next_turn_via_stay(config_factory):
    # The police did not move onto the thief this turn — the thief walked
    # onto the police on ITS turn (no capture, per the test above). On the
    # police's OWN next turn, STAYing while still co-located IS a valid
    # claim: capture triggers.
    config = config_factory(cop_start=(2, 2), thief_start=(2, 3))
    state = MatchState.initial(config, first_mover=Side.THIEF)
    state = apply_move(state, Direction.W)  # thief -> co-located, no capture
    state = next_turn(state, Side.THIEF)
    state = apply_move(state, Direction.STAY)  # police claims from the same cell
    entry = state.move_log[-1]
    assert entry.capture_triggered
    assert entry.capture_claimed_by_police


def test_police_may_instead_let_a_co_located_thief_walk_away(config_factory):
    # If the police does NOT claim (moves elsewhere instead of STAYing), the
    # thief is free to walk away on its own next turn — no capture ever
    # happened, and nothing about the earlier co-location lingers.
    config = config_factory(grid_size=5, cop_start=(2, 2), thief_start=(2, 3))
    state = MatchState.initial(config, first_mover=Side.THIEF)
    state = apply_move(state, Direction.W)  # thief -> co-located, no capture
    state = next_turn(state, Side.THIEF)
    state = apply_move(state, Direction.N)  # police walks away instead of claiming
    assert not state.move_log[-1].capture_triggered
    assert state.cop_pos != state.thief_pos


def test_barrier_on_thief_cell_resolves_as_capture_not_illegal_move(config_factory):
    config = config_factory(cop_start=(2, 1), thief_start=(2, 2))
    state = MatchState.initial(config, first_mover=Side.POLICE)
    # No pytest.raises here on purpose: this must succeed as a placement
    # (it is legal — see rules.test_barrier_on_thief_cell_is_a_legal_placement_not_rejected)
    # and resolve as a capture in the SAME turn, not be bounced as illegal.
    state = apply_barrier(state, Position(2, 2))
    entry = state.move_log[-1]
    assert entry.action_type is ActionType.BARRIER
    assert entry.capture_triggered
    assert entry.capture_claimed_by_police


def test_police_may_trap_itself_and_it_is_legal(config_factory):
    # The police walling itself in is the intended strategic risk of the
    # barrier mechanic (rulebook: "This is legal ... Do not add a rule
    # preventing it"). Placing all four barriers around its own cell must
    # not raise, and STAY must remain legal afterwards even though every
    # other direction is now blocked.
    config = config_factory(cop_start=(2, 2), max_barriers=4)
    state = MatchState.initial(config, first_mover=Side.POLICE)
    cop_pos = state.cop_pos
    neighbours = state.board.orthogonal_neighbors(cop_pos)

    for target in neighbours:
        state = apply_barrier(state, target)  # must not raise

    assert state.barriers_placed == 4
    assert state.cop_pos == cop_pos  # the police never had to move to do this

    assert is_move_legal(state.board, cop_pos, Direction.STAY, config.movement)
    for direction in (Direction.N, Direction.S, Direction.E, Direction.W):
        assert not is_move_legal(state.board, cop_pos, direction, config.movement)


def test_thief_survived_steps_increments_only_on_thief_moves(config):
    state = MatchState.initial(config, first_mover=Side.POLICE)
    state = apply_move(state, Direction.STAY)  # police's turn
    assert state.thief_survived_steps == 0
    state = next_turn(state, Side.POLICE)
    state = apply_move(state, Direction.STAY)  # thief's turn
    assert state.thief_survived_steps == 1


def test_thief_survived_steps_does_not_increment_on_capture(config_factory):
    config = config_factory(cop_start=(2, 2), thief_start=(2, 3))
    state = MatchState.initial(config, first_mover=Side.POLICE)
    state = apply_move(state, Direction.E)  # police lands on thief -> capture, before the thief ever acts
    assert state.thief_survived_steps == 0


def test_thief_survived_steps_increments_on_a_co_location_that_is_not_a_capture(config_factory):
    # PRD-03: the thief walking onto the police is an ordinary, uncaptured
    # move — it must still count toward the thief's own survived-steps
    # budget like any other successful move.
    config = config_factory(cop_start=(2, 2), thief_start=(2, 3))
    state = MatchState.initial(config, first_mover=Side.THIEF)
    state = apply_move(state, Direction.W)  # thief walks onto cop -> no capture
    assert state.thief_survived_steps == 1


def test_thief_survived_steps_counter_is_exact_around_the_threshold(config_factory):
    # Drives the thief's own counter directly, independent of the match
    # loop's stopping logic, across the threshold-1 / threshold / threshold+1
    # boundary, to prove there is no off-by-one drift in the counter itself.
    threshold = 4
    config = config_factory(survival_threshold=threshold)
    state = MatchState.initial(config, first_mover=Side.THIEF)

    for expected in range(1, threshold + 2):  # covers threshold-1, threshold, threshold+1
        state = apply_move(state, Direction.STAY)
        assert state.thief_survived_steps == expected


def test_next_turn_advances_round_only_after_full_cycle(config):
    state = MatchState.initial(config, first_mover=Side.POLICE)
    assert state.turn_number == 1
    state = next_turn(state, Side.POLICE)
    assert state.whose_turn is Side.THIEF
    assert state.turn_number == 1  # still round 1, thief hasn't gone yet
    state = next_turn(state, Side.POLICE)
    assert state.whose_turn is Side.POLICE
    assert state.turn_number == 2  # round advanced now that it's back to first mover
