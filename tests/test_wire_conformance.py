"""Stage-5 close-out: nothing in the suite checked our WIRE SURFACE (tool
names, argument shape, `terms` payload shape) against the interop kit's
conformance vectors — only our hash/crypto CONSTRUCTIONS were checked
(test_vectors.py). That gap was invisible until a live rehearsal against the
kit's sparring peer found it: two real, confirmed deviations (tool names,
`terms` key shape), independently confirmed against BOTH the interop kit's
`vectors/turn_message.json`/`terms_signature.json` (tiers PROMOTED/CORE) and
the professor's own reference implementation
(`ref_impl/src/police_thief/infra/mcp_server.py`,
`ref_impl/src/police_thief/peer/sealing.py::terms_from_config`). This file
makes that class of gap fail in `pytest`, not at match time.

The pinned literal values below are copied from the interop kit's vector
JSON (data, not code — same integrity boundary as tests/fixtures/vectors/,
see its README) and cross-checked against the reference implementation by
hand; they are not re-fetched from either external repo at test time.
"""

from __future__ import annotations

import asyncio

from uoh_mh01.infra.mcp_server import build_server
from uoh_mh01.shared.terms import terms_from_config

# SPEC §7.5 / vectors/turn_message.json (PROMOTED): the four tools, and
# which single argument name each carries — REQUIRED tools only; the fourth,
# OPTIONAL `receive_control`, is checked separately below since a
# conformant peer is allowed to omit it.
_REQUIRED_TOOLS = {
    "negotiate": "message",
    "receive_turn": "message",
    "submit_audit": "payload",
}

# vectors/terms_signature.json (CORE — "the interop floor"): the flat,
# closed 14-key shape `terms_from_config` must reproduce exactly.
_CORE_TERMS_KEYS = frozenset({
    "board_size", "smell_grid_size", "decay_per_step", "emit_intensity",
    "min_center_intensity", "max_steps", "barriers_max", "setting",
    "hint_max_words", "axis_origin_corner", "axis_start_index",
    "thief_start", "cop_start", "num_games",
})


class _FakeHandlers:
    async def receive_opponent_move(self, request): ...
    async def receive_negotiate(self, message): ...
    async def receive_audit_reveal(self, records, sub_game_number): ...


def _registered_tools() -> dict[str, dict]:
    server = build_server(_FakeHandlers())
    tools = asyncio.run(server.list_tools())
    return {t.name: t.parameters for t in tools}


def test_required_tool_names_and_single_dict_argument_match_the_wire_surface():
    tools = _registered_tools()
    for name, arg_name in _REQUIRED_TOOLS.items():
        assert name in tools, f"required tool {name!r} is not registered on our MCP server"
        params = tools[name]
        assert params["required"] == [arg_name], (
            f"{name} must take exactly one required argument named {arg_name!r} "
            f"(SPEC §7.5's documented message/payload asymmetry), got {params['required']!r}"
        )


def test_receive_control_is_present_and_optional():
    # OPTIONAL per SPEC §7.5, but we DO implement it (a real opponent may
    # call it) — still worth pinning the shape so it does not silently
    # drift from `message` if ever touched again.
    tools = _registered_tools()
    assert "receive_control" in tools
    assert tools["receive_control"]["required"] == ["message"]


def test_terms_from_config_matches_the_core_terms_signature_key_shape(config):
    terms = terms_from_config(config)
    assert set(terms) == _CORE_TERMS_KEYS, (
        "terms_from_config's key set has drifted from the interop kit's CORE "
        f"terms_signature vector. missing={_CORE_TERMS_KEYS - set(terms)} "
        f"extra={set(terms) - _CORE_TERMS_KEYS}"
    )


def test_terms_from_config_values_are_the_expected_shapes(config):
    terms = terms_from_config(config)
    assert isinstance(terms["board_size"], int)
    assert isinstance(terms["thief_start"], list) and len(terms["thief_start"]) == 2
    assert isinstance(terms["cop_start"], list) and len(terms["cop_start"]) == 2
    assert isinstance(terms["setting"], str)
    assert isinstance(terms["decay_per_step"], float)
    assert isinstance(terms["emit_intensity"], float)
    assert isinstance(terms["min_center_intensity"], float)
