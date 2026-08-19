"""Driving THIS peer's own active turns.

Split out of orchestrator.py to keep files under the project's ~150-line
budget (mirroring the reference implementation's own peer/turn_sender.py
split — see PRD-02 "Part A findings"). A mixin, not a standalone class, so
PeerRuntime keeps a single ordinary method-call surface
(`self._take_my_turn()`) even though the implementation lives here.
"""

from __future__ import annotations

import logging

from ..domain.hints import enforce_word_cap
from ..domain.match import Action, BarrierAction, MoveAction
from ..domain.reducers import apply_barrier, apply_move
from ..domain.scent import advance_field, emit, serialize_field
from ..domain.scoring import TerminalCondition
from ..domain.terminal_detect import DetectedTerminal, detect_from_last_action, detect_pre_turn
from .protocol_builders import action_to_request, declare_terminal_request
from .state_machine import Phase
from .turn_resolver import _TurnResolverMixin

logger = logging.getLogger(__name__)


class _TurnSenderMixin(_TurnResolverMixin):
    def _apply_own_action(self, action: Action):
        if isinstance(action, MoveAction):
            return apply_move(self.state, action.direction)
        assert isinstance(action, BarrierAction)
        return apply_barrier(self.state, action.target)

    async def _take_my_turn(self) -> None:
        pre_claim = detect_pre_turn(self.state, self.role)
        if pre_claim is not None:
            await self._declare_and_settle(pre_claim)
            return

        self._transition(Phase.COMPUTING_MOVE)
        # PRD-05: a BrainBase-based strategy reads its `belief` attribute
        # inside __call__ — set it immediately before invoking, never
        # passed as a call argument, so the Strategy signature stays
        # exactly Callable[[MatchState, Side], Action] and every pre-
        # existing 2-argument lambda strategy keeps working unchanged.
        if hasattr(self._strategy, "belief"):
            self._strategy.belief = self._belief
        try:
            action: Action = self._strategy(self.state, self.role)
        except Exception:
            logger.exception("local move computation failed")
            self._transition(Phase.TECHNICAL_LOSS)
            self._finish(TerminalCondition.TECHNICAL_LOSS, offending_side=self.role)
            return

        self._transition(Phase.COMMITTING)
        turn_number = self.state.turn_number

        # Apply MY OWN action to MY OWN state — and hand the turn to the
        # opponent — BEFORE sending it. See PRD-02 "Architecture decisions"
        # #3 for the race this closes. Unlike stage 2's first cut, the
        # resulting terminal CLAIM (if any) is not yet trusted as my final
        # outcome — see "Stage 2 corrections" B1: it still has to survive a
        # declare/confirm round trip with the opponent. The commit is sealed
        # AFTER applying, using the entry's own action_type/detail, so the
        # sealed payload and the wire message can never drift apart (PRD-03).
        async with self._lock:
            new_state = self._apply_own_action(action)
            claim = detect_from_last_action(new_state)
            entry = new_state.move_log[-1]
            self.state = new_state
            # PRD-04: deposit + decay MY OWN trail once per my own full turn
            # (book ch.4 cadence), around wherever this action left me — a
            # move, a stay, or a barrier placement all keep the agent
            # somewhere, and that "somewhere" is what gets scented.
            deposit = emit(self._my_position(), new_state.board, self.config.pheromones)
            self._own_scent_field = advance_field(self._own_scent_field, deposit, self.config.pheromones)
            smell_grid = serialize_field(self._own_scent_field)
            # PRD-05: a BrainBase-based strategy stashed (text, is_true) on
            # itself during __call__ above; a plain lambda strategy (tests,
            # or a peer with no brain configured) has none, so hint stays
            # silent rather than inventing a claim on the strategy's behalf.
            hint_text, hint_is_true = getattr(self._strategy, "last_hint", ("", None))
            hint_text = enforce_word_cap(hint_text, self.config.world.hint_max_words)
            commit = self._seal_own_record(
                step=turn_number,
                action_type=entry.action_type.value,
                detail=entry.detail,
                smell_grid=smell_grid,
                hint=hint_text,
                hint_is_true=hint_is_true,
            )
            self.log.record_action(self.state.move_log[-1])
            if claim is None:
                self._advance_turn()

        request = action_to_request(
            action,
            self.role,
            turn_number,
            police_actions_taken=self.state.police_actions_taken,
            thief_actions_taken=self.state.thief_actions_taken,
            claimed_condition=claim.condition if claim else None,
            commit=commit,
            sub_game_number=self.sub_game_number,
            smell_grid=smell_grid,
            hint=hint_text,
            hint_is_true=hint_is_true,
        )
        self._transition(Phase.AWAITING_REVEAL)
        await self._send_and_resolve(request, claim)

    async def _declare_and_settle(self, claim: DetectedTerminal) -> None:
        """Entrapment or the max_moves ceiling: a terminal condition detected
        with NO accompanying move. Declared explicitly rather than just
        going silent — see PRD-02 'Stage 2 corrections' B1."""
        self._transition(Phase.COMPUTING_MOVE)
        self._transition(Phase.COMMITTING)
        turn_number = self.state.turn_number
        commit = self._seal_own_record(step=turn_number, action_type="declare_terminal", detail=claim.condition)
        request = declare_terminal_request(
            self.role,
            turn_number,
            claim.condition,
            police_actions_taken=self.state.police_actions_taken,
            thief_actions_taken=self.state.thief_actions_taken,
            commit=commit,
            sub_game_number=self.sub_game_number,
        )
        self._transition(Phase.AWAITING_REVEAL)
        await self._send_and_resolve(request, claim)
