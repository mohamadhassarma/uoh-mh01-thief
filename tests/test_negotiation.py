from uoh_mh01.domain.state import Side
from uoh_mh01.infra.negotiation import (
    NegotiationRefusedError,
    build_negotiate_message,
    game_ids,
    verify_peer_message,
)
from uoh_mh01.shared.peer_config import PeerConfig


def _peer_config(group_id: str, port: int) -> PeerConfig:
    return PeerConfig(
        role="police",
        group_id=group_id,
        group_name=f"Team {group_id}",
        my_port=port,
        opponent_url="http://127.0.0.1:9999/mcp",
        turn_timeout_seconds=30,
        members=("a", "b"),
        repos={"cop": "https://example.invalid"},
    )


def test_matching_terms_and_complementary_roles_verify_cleanly(config):
    mine = build_negotiate_message(Side.POLICE, config, _peer_config("alpha", 1), sub_game_number=1)
    theirs = build_negotiate_message(Side.THIEF, config, _peer_config("bravo", 2), sub_game_number=1)
    verify_peer_message(mine, theirs)  # must not raise


def test_terms_mismatch_refuses(config, config_factory):
    other_config = config_factory(grid_size=9)
    mine = build_negotiate_message(Side.POLICE, config, _peer_config("alpha", 1), sub_game_number=1)
    theirs = build_negotiate_message(Side.THIEF, other_config, _peer_config("bravo", 2), sub_game_number=1)
    try:
        verify_peer_message(mine, theirs)
        raise AssertionError("expected NegotiationRefusedError")
    except NegotiationRefusedError as exc:
        assert "terms mismatch" in str(exc)


def test_sub_game_number_desync_refuses(config):
    mine = build_negotiate_message(Side.POLICE, config, _peer_config("alpha", 1), sub_game_number=1)
    theirs = build_negotiate_message(Side.THIEF, config, _peer_config("bravo", 2), sub_game_number=2)
    try:
        verify_peer_message(mine, theirs)
        raise AssertionError("expected NegotiationRefusedError")
    except NegotiationRefusedError as exc:
        assert "sub_game_number mismatch" in str(exc)


def test_same_role_on_both_sides_refuses(config):
    mine = build_negotiate_message(Side.POLICE, config, _peer_config("alpha", 1), sub_game_number=1)
    theirs = build_negotiate_message(Side.POLICE, config, _peer_config("bravo", 2), sub_game_number=1)
    try:
        verify_peer_message(mine, theirs)
        raise AssertionError("expected NegotiationRefusedError")
    except NegotiationRefusedError as exc:
        assert "roles must be complementary" in str(exc)


def test_forged_signature_refuses(config):
    mine = build_negotiate_message(Side.POLICE, config, _peer_config("alpha", 1), sub_game_number=1)
    theirs = build_negotiate_message(Side.THIEF, config, _peer_config("bravo", 2), sub_game_number=1)
    import dataclasses

    forged = dataclasses.replace(theirs, signature="0" * 64)
    try:
        verify_peer_message(mine, forged)
        raise AssertionError("expected NegotiationRefusedError")
    except NegotiationRefusedError as exc:
        assert "signature does not verify" in str(exc)


def test_game_ids_order_independent(config):
    mine = build_negotiate_message(Side.POLICE, config, _peer_config("alpha", 1), sub_game_number=1)
    theirs = build_negotiate_message(Side.THIEF, config, _peer_config("bravo", 2), sub_game_number=1)
    id_ab, uid_ab = game_ids(mine, theirs)
    id_ba, uid_ba = game_ids(theirs, mine)
    assert id_ab == id_ba == "alpha-vs-bravo"
    assert uid_ab == uid_ba
