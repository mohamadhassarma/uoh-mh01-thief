import pytest

from uoh_mh01.domain.config import ConfigError, load_config, parse_config

from .conftest import REAL_CONFIG_PATH, make_raw_config


def test_real_config_loads_and_validates():
    config = load_config(REAL_CONFIG_PATH)
    assert config.board.grid_size == 7
    assert config.board.thief_start == (3, 3)
    assert config.board.cop_start == (0, 0)
    assert config.movement.max_barriers == 14
    assert config.movement.max_moves == 35
    assert config.movement.survival_threshold == 35
    assert config.network.response_timeout_sec == 30
    assert config.network.watchdog_timeout_sec == 60
    assert config.scoring.capture_cop == 20
    assert config.scoring.tie_score == 2


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
