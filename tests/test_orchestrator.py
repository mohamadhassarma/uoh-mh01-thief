import asyncio
import dataclasses

import uoh_mh01.infra.mcp_client as mcp_client_module
from uoh_mh01.domain.board import Direction
from uoh_mh01.domain.match import MoveAction
from uoh_mh01.domain.state import Side
from uoh_mh01.infra.watchdog import OpponentUnresponsiveError
from uoh_mh01.orchestrator import PeerRuntime
from uoh_mh01.shared.peer_config import PeerConfig


def _peer_config(role: str = "police", my_port: int = 8801, opponent_port: int = 8802, turn_timeout_seconds: float = 5) -> PeerConfig:
    return PeerConfig(
        role=role,
        group_id="test-group",
        group_name="Test Group",
        my_port=my_port,
        opponent_url=f"http://127.0.0.1:{opponent_port}/mcp",
        turn_timeout_seconds=turn_timeout_seconds,
    )


def test_taking_my_turn_seals_a_real_commit_record(config_factory):
    # PRD-03 acceptance criterion: the stage-2 placeholders are gone, real
    # commit-reveal sealing happened instead. This does not need a network
    # call — sealing happens locally before anything is sent.
    from uoh_mh01.domain.crypto import verify

    config = config_factory()
    runtime = PeerRuntime(Side.POLICE, config, _peer_config(), strategy=lambda state, side: MoveAction(Direction.E))
    record = runtime._seal_own_record(step=1, action_type="move", detail="E")
    sealed = runtime.own_sealed_records[-1]
    assert sealed["commit"] == record
    assert verify(sealed["payload"], sealed["nonce"], sealed["commit"])


async def test_silent_opponent_produces_technical_loss_not_a_hang(config_factory, monkeypatch):
    async def _always_unresponsive(*args, **kwargs):
        raise OpponentUnresponsiveError("submit_move", 0.01)

    monkeypatch.setattr(mcp_client_module, "send_move", _always_unresponsive)

    config = config_factory(watchdog_timeout_sec=0.05)
    runtime = PeerRuntime(
        Side.POLICE,
        config,
        _peer_config(),
        strategy=lambda state, side: MoveAction(Direction.E),
    )

    # Wrapped in an outer timeout as a test-correctness safety net: this
    # assertion is exactly "does not hang" — if the implementation ever
    # regressed into a real hang, this fails loudly instead of stalling CI.
    outcome = await asyncio.wait_for(runtime.run_match(), timeout=10)

    assert outcome.terminal_condition.value == "technical_loss"
    assert outcome.offending_side is Side.THIEF
    assert outcome.police_score == config.scoring.technical_loss
    assert outcome.thief_score == config.scoring.technical_loss


async def test_opponent_rejection_produces_technical_loss_for_the_sender(config_factory, monkeypatch):
    from uoh_mh01.infra.protocol_response import MoveResponse

    async def _rejects(*args, **kwargs):
        return MoveResponse(accepted=False, reason="opponent said no")

    monkeypatch.setattr(mcp_client_module, "send_move", _rejects)

    config = config_factory()
    runtime = PeerRuntime(
        Side.POLICE,
        config,
        _peer_config(),
        strategy=lambda state, side: MoveAction(Direction.E),
    )
    # Explicit, independent of whichever side FIRST_MOVER happens to be:
    # this test is about MY OWN outbound send failing, which requires it to
    # be MY turn.
    runtime.state = dataclasses.replace(runtime.state, whose_turn=Side.POLICE)

    outcome = await asyncio.wait_for(runtime.run_match(), timeout=10)

    assert outcome.terminal_condition.value == "technical_loss"
    assert outcome.offending_side is Side.POLICE  # I sent it; it was rejected; that's on me


async def test_divergence_response_produces_unscored_technical_loss(config_factory, monkeypatch):
    from uoh_mh01.infra.protocol_response import MoveResponse

    async def _diverges(*args, **kwargs):
        return MoveResponse(accepted=False, divergence="counter mismatch: sender claims police=9 thief=0, ...")

    monkeypatch.setattr(mcp_client_module, "send_move", _diverges)

    config = config_factory()
    runtime = PeerRuntime(
        Side.POLICE,
        config,
        _peer_config(),
        strategy=lambda state, side: MoveAction(Direction.E),
    )
    # Explicit, independent of whichever side FIRST_MOVER happens to be:
    # this test needs MY OWN send_move call to actually fire.
    runtime.state = dataclasses.replace(runtime.state, whose_turn=Side.POLICE)

    outcome = await asyncio.wait_for(runtime.run_match(), timeout=10)

    assert outcome.terminal_condition.value == "technical_loss"
    assert outcome.offending_side is None  # a divergence has no single attributable guilty party
    assert outcome.police_score == config.scoring.technical_loss
    assert outcome.thief_score == config.scoring.technical_loss


async def test_turn_timeout_seconds_self_forfeits_independently_of_watchdog_timeout_sec(config_factory, monkeypatch):
    async def _always_unresponsive(*args, **kwargs):
        raise OpponentUnresponsiveError("submit_move", 0.01)

    monkeypatch.setattr(mcp_client_module, "send_move", _always_unresponsive)

    # watchdog_timeout_sec is deliberately loose: only my own private
    # turn_timeout_seconds should be able to fire this quickly.
    config = config_factory(watchdog_timeout_sec=10)
    runtime = PeerRuntime(
        Side.POLICE,
        config,
        _peer_config(turn_timeout_seconds=0.05),
        strategy=lambda state, side: MoveAction(Direction.E),
    )
    # Explicit, independent of whichever side FIRST_MOVER happens to be:
    # this test needs it to be MY turn so MY OWN turn_timeout_seconds budget
    # is what fires.
    runtime.state = dataclasses.replace(runtime.state, whose_turn=Side.POLICE)

    outcome = await asyncio.wait_for(runtime.run_match(), timeout=10)

    assert outcome.terminal_condition.value == "technical_loss"
    assert outcome.offending_side is Side.POLICE  # I blew my own private per-turn budget


async def test_turn_timeout_seconds_forfeits_a_silent_opponent_before_the_looser_watchdog_would(config_factory):
    # Nobody ever calls receive_opponent_move — a genuinely silent opponent,
    # with a watchdog_timeout_sec loose enough that only turn_timeout_seconds
    # should be able to catch this quickly.
    config = config_factory(watchdog_timeout_sec=10)
    runtime = PeerRuntime(
        Side.THIEF,
        config,
        _peer_config(role="thief", turn_timeout_seconds=0.05),
        strategy=lambda state, side: MoveAction(Direction.E),
    )
    # Explicit, independent of whichever side FIRST_MOVER happens to be:
    # this test is about waiting for an opponent who never moves, so it must
    # start on the OPPONENT's turn, not mine.
    runtime.state = dataclasses.replace(runtime.state, whose_turn=Side.POLICE)

    outcome = await asyncio.wait_for(runtime.run_match(), timeout=10)

    assert outcome.terminal_condition.value == "technical_loss"
    assert outcome.offending_side is Side.POLICE  # the opponent went silent past MY private budget


async def test_freeze_detected_with_no_narrower_timeout_still_resolves_to_technical_loss(config_factory):
    # This is the DEFAULT-CONFIG shape (turn_timeout_seconds 180 > watchdog_
    # timeout_sec 60, scaled down here for a fast test): a genuinely silent
    # opponent on ITS OWN turn is caught by neither the active-turn budget
    # (it's not my turn) nor _wait_for_opponent's own turn_timeout_seconds
    # check (the watchdog is the TIGHTER of the two here), so the top-of-loop
    # watchdog.assert_alive() is what actually fires — FreezeDetected MUST
    # still resolve to a reportable TECHNICAL_LOSS, never propagate as a bare
    # exception (PRD-02 "Stage 2 corrections", round 2): rule #35 has no
    # "the protocol didn't resolve" case.
    config = config_factory(watchdog_timeout_sec=0.05)
    runtime = PeerRuntime(
        Side.THIEF,
        config,
        _peer_config(role="thief", turn_timeout_seconds=1.0),  # looser than the watchdog
        strategy=lambda state, side: MoveAction(Direction.E),
    )
    # Explicit, independent of whichever side FIRST_MOVER happens to be:
    # this test needs to start on the OPPONENT's (police's) turn.
    runtime.state = dataclasses.replace(runtime.state, whose_turn=Side.POLICE)

    outcome = await asyncio.wait_for(runtime.run_match(), timeout=10)

    assert outcome.terminal_condition.value == "technical_loss"
    assert outcome.offending_side is Side.POLICE  # police never moved; it was police's turn
    assert outcome.police_score == config.scoring.technical_loss
    assert outcome.thief_score == config.scoring.technical_loss


async def test_unconfirmed_claim_after_opponent_silence_is_recorded_in_the_log(config_factory, monkeypatch):
    # "Declared and then SILENCE" (PRD-02 "Stage 2 corrections", round 2):
    # the claim itself must survive in the log for the audit even though the
    # score is still the symmetric, unscored technical-loss pair — losing
    # the claim from the record would make it useless for exactly the
    # dispute it's meant to help resolve later.
    async def _always_unresponsive(*args, **kwargs):
        raise OpponentUnresponsiveError("submit_move", 0.01)

    monkeypatch.setattr(mcp_client_module, "send_move", _always_unresponsive)

    # cop_start adjacent to thief_start so the very first move is a claimed capture.
    config = config_factory(grid_size=5, cop_start=(2, 2), thief_start=(2, 3), watchdog_timeout_sec=0.05)
    runtime = PeerRuntime(
        Side.POLICE,
        config,
        _peer_config(),
        strategy=lambda state, side: MoveAction(Direction.E),
    )
    # Explicit, independent of whichever side FIRST_MOVER happens to be:
    # this test needs MY OWN move (the claimed capture) to actually be
    # attempted, which requires it to be my turn.
    runtime.state = dataclasses.replace(runtime.state, whose_turn=Side.POLICE)

    outcome = await asyncio.wait_for(runtime.run_match(), timeout=10)

    assert outcome.terminal_condition.value == "technical_loss"
    assert outcome.offending_side is Side.THIEF
    assert runtime.log.unconfirmed_claim == "capture_landing"
