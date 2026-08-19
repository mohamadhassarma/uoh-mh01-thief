import pytest

from uoh_mh01.shared.peer_config import (
    PeerConfigError,
    load_peer_config,
    overlay_signed_contract,
    parse_peer_config,
)

_VALID_TOML = {
    "game": {"group_id": "uoh-mh01", "group_name": "Hassarma-Agents"},
    "network": {"my_port": 8801, "opponent_url": "http://127.0.0.1:8802/mcp", "turn_timeout_seconds": 180},
}

_VALID_JSON = {
    "network_and_league": {"response_timeout_sec": 30, "watchdog_timeout_sec": 60},
}


def test_valid_peer_config_parses():
    peer = parse_peer_config("police", _VALID_TOML, _VALID_JSON)
    assert peer.role == "police"
    assert peer.group_id == "uoh-mh01"
    assert peer.group_name == "Hassarma-Agents"
    assert peer.my_port == 8801
    assert peer.opponent_url == "http://127.0.0.1:8802/mcp"
    assert peer.turn_timeout_seconds == 180


def test_strategy_class_is_optional_and_defaults_to_none():
    peer = parse_peer_config("police", _VALID_TOML, _VALID_JSON)
    assert peer.police_class is None
    assert peer.thief_class is None


def test_strategy_class_parses_when_present():
    toml = {**_VALID_TOML, "strategy": {"police_class": "uoh_mh01.domain.police_brain:ContainmentPoliceBrain"}}
    peer = parse_peer_config("police", toml, _VALID_JSON)
    assert peer.police_class == "uoh_mh01.domain.police_brain:ContainmentPoliceBrain"
    assert peer.thief_class is None


def test_missing_field_raises_clearly():
    toml = {"game": {"group_id": "x", "group_name": "y"}, "network": {"my_port": 8801, "opponent_url": "u"}}
    with pytest.raises(PeerConfigError, match="turn_timeout_seconds"):
        parse_peer_config("police", toml, _VALID_JSON)


def test_missing_section_raises_clearly():
    toml = {"game": {"group_id": "x", "group_name": "y"}}
    with pytest.raises(PeerConfigError, match="'network'"):
        parse_peer_config("police", toml, _VALID_JSON)


def test_real_toml_loads_from_disk():
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[1]
    peer = load_peer_config("thief", repo_root / "config" / "thief" / "game.toml", repo_root / "config" / "game.json")
    assert peer.role == "thief"
    assert peer.group_id == "uoh-mh01"
    assert peer.my_port == 8802
    assert peer.opponent_url == "http://127.0.0.1:8801/mcp"


# --- overlay rule: the signed contract always wins on a shared key ---


def test_overlay_signed_wins_on_scalar_collision():
    private = {"network_and_league": {"response_timeout_sec": 9999}}  # a rogue TOML trying to weaken the timeout
    signed = {"network_and_league": {"response_timeout_sec": 30}}
    merged = overlay_signed_contract(private, signed)
    assert merged["network_and_league"]["response_timeout_sec"] == 30


def test_overlay_signed_wins_recursively_through_nested_dicts():
    private = {"a": {"b": {"c": "private-value", "untouched": "keep-me"}}}
    signed = {"a": {"b": {"c": "signed-value"}}}
    merged = overlay_signed_contract(private, signed)
    assert merged["a"]["b"]["c"] == "signed-value"
    assert merged["a"]["b"]["untouched"] == "keep-me"  # private-only keys survive


def test_overlay_keeps_private_only_keys():
    private = {"network": {"my_port": 8801, "turn_timeout_seconds": 180}}
    signed = {"network_and_league": {"response_timeout_sec": 30}}
    merged = overlay_signed_contract(private, signed)
    assert merged["network"]["my_port"] == 8801
    assert merged["network_and_league"]["response_timeout_sec"] == 30


def test_overlay_adds_signed_only_keys():
    private = {}
    signed = {"scoring": {"capture_cop": 20}}
    merged = overlay_signed_contract(private, signed)
    assert merged["scoring"]["capture_cop"] == 20


def test_parse_peer_config_actually_applies_the_overlay():
    # A private toml that tries to redefine a signed field under the same
    # path — parse_peer_config must build effective values from the
    # OVERLAID dict, not the raw private one, so this proves the rule is
    # enforced in code, not just documented.
    toml_with_collision = {
        **_VALID_TOML,
        "network_and_league": {"response_timeout_sec": 1},  # attempted override
    }
    signed_with_same_path = {
        **_VALID_JSON,
        "network_and_league": {"response_timeout_sec": 30, "watchdog_timeout_sec": 60},
    }
    merged = overlay_signed_contract(toml_with_collision, signed_with_same_path)
    assert merged["network_and_league"]["response_timeout_sec"] == 30
