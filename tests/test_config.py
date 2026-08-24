import pytest

from uoh_mh01.domain.config import ConfigError, load_config, parse_config

from .conftest import REAL_CONFIG_PATH, make_raw_config


def test_real_config_loads_and_validates():
    """The SHIPPED contract must load and be internally coherent.

    Deliberately does NOT pin the negotiated values. Most of what this test
    used to assert is in the flat 14-key set the pre-game handshake signs
    (`shared/terms.py`) - board size, both starts, `barriers_max`,
    `max_steps`, `num_games` - and the timeouts are agreed per opponent out
    of band. Pinning them made the suite fail the moment we legitimately
    agreed 180/180 with khm-mn17: a red that says nothing about the code and
    everything about a test asserting one particular negotiation.

    What IS asserted here is what the parser cannot already guarantee.
    `config_validators` enforces types, positivity and coordinate bounds, so
    repeating those would be vacuous; these are the cross-field properties it
    does not check.
    """
    config = load_config(REAL_CONFIG_PATH)

    # The two agents cannot start on the same cell - that would be a capture
    # before either side has moved.
    assert config.board.cop_start != config.board.thief_start

    # A freeze detector tighter than a single request would fire during a
    # perfectly legitimate call.
    assert config.network.watchdog_timeout_sec >= config.network.response_timeout_sec

    # App. F table 20's scoring is league-wide and fixed - it is NOT part of
    # the signed terms and no opponent can negotiate it, so a change here
    # would be a real defect rather than a new agreement.
    assert (config.scoring.capture_cop, config.scoring.capture_thief) == (20, 5)
    assert (config.scoring.survival_cop, config.scoring.survival_thief) == (5, 10)
    assert (config.scoring.tie_score, config.scoring.technical_loss) == (2, 0)


def test_the_shipped_config_can_actually_be_negotiated():
    """The strongest "this config is valid" check available: it must produce
    the exact flat term set a handshake signs. Both outside authorities do a
    strict dict-equality check on it, so a missing or extra key refuses the
    handshake against every conformant opponent."""
    from uoh_mh01.shared.terms import terms_from_config

    terms = terms_from_config(load_config(REAL_CONFIG_PATH))
    assert len(terms) == 14
    assert not [key for key, value in terms.items() if value is None]


def test_missing_field_raises_clearly():
    raw = make_raw_config()
    del raw["board_and_agents"]["grid_size"]
    with pytest.raises(ConfigError, match="grid_size"):
        parse_config(raw)


def test_missing_section_raises_clearly():
    raw = make_raw_config()
    del raw["scoring"]
    with pytest.raises(ConfigError, match="scoring"):
        parse_config(raw)


def test_malformed_json_raises_clearly(tmp_path):
    bad_file = tmp_path / "game.json"
    bad_file.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(bad_file)


def test_missing_file_raises_clearly(tmp_path):
    with pytest.raises(ConfigError):
        load_config(tmp_path / "does-not-exist.json")


def test_unsupported_axis_origin_corner_rejected():
    raw = make_raw_config()
    raw["board_and_agents"]["axis_origin_corner"] = "bottom-right"
    with pytest.raises(ConfigError, match="axis_origin_corner"):
        parse_config(raw)


def test_unsupported_axis_start_index_rejected():
    raw = make_raw_config()
    raw["board_and_agents"]["axis_start_index"] = 1
    with pytest.raises(ConfigError, match="axis_start_index"):
        parse_config(raw)


def test_same_start_cell_rejected():
    raw = make_raw_config(thief_start=(2, 2), cop_start=(2, 2))
    with pytest.raises(ConfigError, match="same cell"):
        parse_config(raw)


def test_out_of_bounds_start_rejected():
    raw = make_raw_config(grid_size=5, thief_start=(9, 9))
    with pytest.raises(ConfigError, match="out of bounds"):
        parse_config(raw)


def test_wrong_move_set_rejected():
    raw = make_raw_config()
    raw["movement_and_barriers"]["move_set"] = ["N", "S", "E", "W"]  # missing STAY
    with pytest.raises(ConfigError, match="move_set"):
        parse_config(raw)


def test_non_positive_grid_size_rejected():
    raw = make_raw_config()
    raw["board_and_agents"]["grid_size"] = 0
    with pytest.raises(ConfigError):
        parse_config(raw)


def test_negative_score_rejected():
    raw = make_raw_config()
    raw["scoring"]["capture_cop"] = -1
    with pytest.raises(ConfigError):
        parse_config(raw)


def test_missing_network_section_raises_clearly():
    raw = make_raw_config()
    del raw["network_and_league"]
    with pytest.raises(ConfigError, match="network_and_league"):
        parse_config(raw)


def test_non_positive_response_timeout_rejected():
    raw = make_raw_config()
    raw["network_and_league"]["response_timeout_sec"] = 0
    with pytest.raises(ConfigError, match="response_timeout_sec"):
        parse_config(raw)
