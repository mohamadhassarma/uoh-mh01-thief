"""The in-game turn-exchange contract from `docs/WIRE.md`, extracted from the
professor's reference implementation (github.com/rmisegal/Game-P2P-Cop-Chase
v3.0.0 — authoritative) and the student interop kit
(github.com/Imreec/copthief-league-protocol).

MIGRATION STATE — COMPLETE. Message shape, state model, audit and transport
all conform; no case is xfail-marked any more.

The live path emits `build_turn_message` and parses `parse_turn_message`, all
four tools are ack-only, and the poll loop drains the inboxes they fill.

DO NOT relax an assertion to make a case pass.
"""

from __future__ import annotations

import asyncio
import re

import pytest

from uoh_mh01.domain.crypto import seal
from uoh_mh01.infra.audit import ReceivedCommitLog, verify_revealed
from uoh_mh01.infra.inboxes import Inboxes
from uoh_mh01.infra.mcp_server import build_server
from uoh_mh01.infra.protocol import ProtocolError
from uoh_mh01.infra.turn_message_builders import build_turn_message, parse_turn_message

# --- the contract, verbatim from docs/WIRE.md §2 -------------------------------

REFERENCE_REQUIRED = ("step", "sender", "hint", "smell_grid", "commit", "timestamp")
REFERENCE_OPTIONAL = ("barrier_placed", "capture_claim", "claim_response", "win_claim")
REFERENCE_TURN_KEYS = frozenset(REFERENCE_REQUIRED + REFERENCE_OPTIONAL)

# Fields whose presence would disclose the mover's move in the clear. The
# reference seals all of these inside `commit` (protocol.py:16-18); nothing
# equivalent may appear on the wire.
MUST_NOT_APPEAR = ("direction", "target_row", "target_col", "action_type", "position", "move")

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _reference_turn_message(**overrides) -> dict:
    """A well-formed inbound TurnMessage exactly as the reference sends one —
    the shape our `receive_turn` must accept. Mirrors the `accept` case in
    interop_kit/vectors/turn_message.json."""
    message = {
        "step": 7,
        "sender": "police",
        "hint": "north of the park",
        "smell_grid": {"3,3": 0.9, "3,4": 0.5, "4,3": 0.5},
        "commit": "a" * 64,
        "timestamp": "2026-08-08T19:00:00Z",
        "barrier_placed": [5, 6],
        "capture_claim": None,
        "claim_response": None,
        "win_claim": None,
    }
    message.update(overrides)
    return message


def _our_outbound_wire_dict() -> dict:
    """What THIS implementation puts on the wire for one ordinary move."""
    return build_turn_message(
        step=7,
        sender="police",
        hint="north of the park",
        smell_grid={"3,3": 0.9},
        commit="a" * 64,
    ).to_wire()




# --- §2: the TurnMessage field set ---------------------------------------------


def test_outbound_turn_message_key_set_matches_the_reference():
    assert frozenset(_our_outbound_wire_dict()) == REFERENCE_TURN_KEYS


def test_outbound_turn_message_carries_every_required_field():
    wire = _our_outbound_wire_dict()
    missing = [name for name in REFERENCE_REQUIRED if name not in wire]
    assert missing == []


def test_outbound_turn_message_does_not_disclose_the_move_in_the_clear():
    wire = _our_outbound_wire_dict()
    disclosed = [name for name in MUST_NOT_APPEAR if name in wire]
    assert disclosed == []


def test_outbound_turn_message_timestamp_is_present_and_non_empty():
    wire = _our_outbound_wire_dict()
    assert isinstance(wire.get("timestamp"), str) and wire["timestamp"].strip()


# --- §3: inbound validation -----------------------------------------------------


def test_inbound_reference_shaped_turn_message_is_accepted():
    parse_turn_message(_reference_turn_message())


def _validator():
    """The target entry point: a pure validator run BEFORE any state change
    (WIRE.md §3). No such function exists today — that is the divergence.

    Deliberately fetched by name rather than imported at module scope, so this
    file still collects and the other cases still report."""
    from uoh_mh01.infra import protocol

    return getattr(protocol, "validate_turn_message", None)


def test_a_pre_state_change_turn_validator_exists():
    assert _validator() is not None, "expected uoh_mh01.infra.protocol.validate_turn_message"


@pytest.mark.parametrize(
    "bad,why",
    [
        ({"commit": "A" * 64}, "uppercase hex refused — commit is compared as a string"),
        ({"commit": None}, "missing commit refused — never defaulted"),
        ({"timestamp": ""}, "empty timestamp refused"),
        ({"step": -1}, "negative step refused"),
        ({"smell_grid": {"3,3": "0.9"}}, "stringified intensity refused"),
    ],
)
def test_inbound_malformed_turn_message_is_refused(bad, why):
    validate = _validator()
    assert validate is not None, "no validate_turn_message() to exercise"
    message = _reference_turn_message(**bad)
    if bad.get("commit") is None:
        message.pop("commit")
    with pytest.raises(ProtocolError):
        validate(message)


def test_inbound_well_formed_turn_message_is_accepted_by_the_validator():
    validate = _validator()
    assert validate is not None, "no validate_turn_message() to exercise"
    validate(_reference_turn_message())


def test_inbound_unknown_key_is_tolerated():
    parse_turn_message(_reference_turn_message(unknown_field={"anything": 1}))


def test_inbound_commit_shape_is_enforced():
    validate = _validator()
    assert validate is not None, "no validate_turn_message() to exercise"
    # Our own sealing already produces conformant hex — the gap is that nothing
    # checks the OPPONENT's.
    assert _HEX64.match(seal({"step": 1, "role": "police"})["commit"])
    with pytest.raises(ProtocolError):
        validate(_reference_turn_message(commit="not-hex"))


# --- §1/§4: the tools acknowledge only, work happens in the poll loop -----------


def test_receive_turn_acknowledges_only():
    inboxes = Inboxes()
    server = build_server(inboxes)

    async def call():
        from fastmcp import Client

        async with Client(server) as client:
            return await client.call_tool("receive_turn", {"message": _reference_turn_message()})

    assert asyncio.run(call()).data == {"ok": True}
    # ...and the message was ENQUEUED, not processed inside the handler.
    assert len(inboxes.turns) == 1


def test_submit_audit_acknowledges_only():
    inboxes = Inboxes()
    server = build_server(inboxes)

    async def call():
        from fastmcp import Client

        async with Client(server) as client:
            return await client.call_tool(
                "submit_audit",
                {"payload": {"sender": "police", "records": [], "result_claim": "survival"}},
            )

    assert asyncio.run(call()).data == {"ok": True}
    assert len(inboxes.audits) == 1


def test_every_tool_acknowledges_only_and_enqueues():
    """All four, including the two that never had a verdict to return."""
    inboxes = Inboxes()
    server = build_server(inboxes)

    async def call_all():
        from fastmcp import Client

        async with Client(server) as client:
            for tool, arg in (
                ("negotiate", "message"),
                ("receive_turn", "message"),
                ("submit_audit", "payload"),
                ("receive_control", "message"),
            ):
                result = await client.call_tool(tool, {arg: {"probe": True}})
                assert result.data == {"ok": True}, tool

    asyncio.run(call_all())
    assert (len(inboxes.agreements), len(inboxes.turns), len(inboxes.audits), len(inboxes.controls)) == (1, 1, 1, 1)


# --- §5: AuditPayload ------------------------------------------------------------


def test_audit_reveal_accepts_the_reference_full_chain_record_shape():
    payload = {"step": 1, "role": "police", "action_type": "move", "detail": "N"}
    sealed = seal(payload)
    log = ReceivedCommitLog()
    # Only the COMMIT is kept from play — the payload arrives in the reveal.
    log.record(1, sealed["commit"])

    reference_records = [{"payload": payload, "nonce": sealed["nonce"], "commit": sealed["commit"]}]
    assert verify_revealed(reference_records, log).passed


def test_audit_payload_carries_sender_and_result_claim():
    from uoh_mh01.domain import sealed_payload

    build = getattr(sealed_payload, "build_audit_payload", None)
    assert build is not None, "no build_audit_payload() exists yet"
    assert frozenset(build(sender="police", records=[], result_claim="survival")) == frozenset(
        ("sender", "records", "result_claim")
    )
