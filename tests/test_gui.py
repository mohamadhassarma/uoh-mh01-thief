"""The viewer's non-Tk half: scene building, live snapshots, replay frames.

None of this opens a window. Everything the viewer decides - colours, labels,
which cell is hot - lives in `gui/scene.py` precisely so it can be asserted
here, on a box with no display.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from uoh_mh01.gui import live_state, replay_frames
from uoh_mh01.gui.capture import write_png
from uoh_mh01.gui.scene import BARRIER, HEAT_COLD, HEAT_HOT, build_scene, heat_colour

REPO_ROOT = Path(__file__).resolve().parents[1]


def _snapshot(**overrides):
    base = {
        "grid_size": 3,
        "role": "police",
        "sub_game_number": 2,
        "step": 7,
        "whose_turn": "police",
        "own_pos": [0, 0],
        "barriers": [],
        "belief": [[0.0, 0.0, 0.0], [0.0, 0.5, 0.0], [0.0, 0.0, 0.25]],
        "game_id": "them-vs-us",
        "result": None,
    }
    return {**base, **overrides}


def _cell(scene, row, col):
    return next(c for c in scene.cells if c.row == row and c.col == col)


# --- the heatmap ----------------------------------------------------------------


def test_the_coldest_and_hottest_colours_are_the_declared_endpoints():
    assert heat_colour(0.0) == "#" + "".join(f"{c:02x}" for c in HEAT_COLD)
    assert heat_colour(1.0) == "#" + "".join(f"{c:02x}" for c in HEAT_HOT)


def test_intensity_is_clamped_rather_than_producing_an_invalid_colour():
    assert heat_colour(-5.0) == heat_colour(0.0)
    assert heat_colour(99.0) == heat_colour(1.0)


def test_cells_redden_monotonically_with_intensity():
    reds = [int(heat_colour(i / 10).lstrip("#")[0:2], 16) for i in range(11)]
    assert reds == sorted(reds)
    assert reds[0] < reds[-1]


def test_heat_is_scaled_against_the_peak_not_the_absolute_probability():
    """A belief map is a distribution: on a real board every cell is a small
    number, so painting absolute probability gives a uniformly black picture
    that shows nothing."""
    scene = build_scene(_snapshot())
    assert _cell(scene, 1, 1).fill == heat_colour(1.0), "the peak cell must be fully hot"
    assert _cell(scene, 2, 2).fill == heat_colour(0.5), "half the peak must be half hot"
    assert _cell(scene, 0, 1).fill == heat_colour(0.0)


def test_a_flat_belief_does_not_divide_by_zero():
    scene = build_scene(_snapshot(belief=[[0.0] * 3 for _ in range(3)]))
    assert all(cell.fill == heat_colour(0.0) for cell in scene.cells if not cell.barrier)


def test_the_peak_cell_is_marked_for_greyscale_readers():
    scene = build_scene(_snapshot())
    assert [(c.row, c.col) for c in scene.cells if c.peak] == [(1, 1)]


# --- structure ------------------------------------------------------------------


def test_barriers_are_painted_as_structure_never_as_heat():
    """A barrier can hold no belief mass by construction (domain/belief.py), so
    colouring one by its belief value would be drawing a quantity that cannot
    exist."""
    scene = build_scene(_snapshot(barriers=[[1, 1]]))
    barrier = _cell(scene, 1, 1)
    assert barrier.barrier and barrier.fill == BARRIER
    assert not barrier.peak
    # ...and the peak moves to the hottest cell that is actually reachable.
    assert [(c.row, c.col) for c in scene.cells if c.peak] == [(2, 2)]


def test_own_position_is_marked_and_is_the_only_one():
    scene = build_scene(_snapshot(own_pos=[2, 1]))
    assert [(c.row, c.col) for c in scene.cells if c.own] == [(2, 1)]


def test_every_cell_of_the_grid_is_painted():
    scene = build_scene(_snapshot(grid_size=7))
    assert len(scene.cells) == 49


# --- the HUD --------------------------------------------------------------------


def test_the_hud_shows_sub_game_role_and_whose_turn():
    hud = dict(build_scene(_snapshot()).hud)
    assert hud["sub-game"] == "2"
    assert hud["my role"] == "police"
    assert "step 7" in hud["turn"] and "MY TURN" in hud["turn"]


def test_the_turn_indicator_distinguishes_waiting_from_playing():
    hud = dict(build_scene(_snapshot(whose_turn="thief")).hud)
    assert "waiting for opponent" in hud["turn"]


def test_the_footer_never_implies_the_opponent_position_is_known():
    """A viewer that looked like it knew where the opponent was would
    misrepresent the whole protocol."""
    assert "NOT known" in build_scene(_snapshot()).footer


def test_a_finished_sub_game_says_so():
    assert "FINISHED" in build_scene(_snapshot(result="capture_landing")).footer


def test_the_heat_label_follows_what_the_heat_actually_is():
    """Live it is belief about the opponent; in a replay it is this agent's own
    transmitted scent. Calling both "belief" would be a lie in one of them."""
    live = build_scene(_snapshot())
    replayed = build_scene(_snapshot(heat_label="own scent"))
    assert any(name == "belief peak" for name, _ in live.hud)
    assert any(name == "own scent peak" for name, _ in replayed.hud)
    assert "own scent" in replayed.footer


# --- the live snapshot ----------------------------------------------------------


def test_a_snapshot_round_trips_through_disk(tmp_path):
    path = tmp_path / "live_state.json"
    live_state.write(path, _snapshot())
    assert live_state.read(path) == _snapshot()


def test_reading_a_missing_or_half_written_snapshot_returns_none(tmp_path):
    assert live_state.read(tmp_path / "nope.json") is None
    broken = tmp_path / "broken.json"
    broken.write_text('{"grid_size": 3', encoding="utf-8")
    assert live_state.read(broken) is None


def test_publishing_writes_only_when_something_a_viewer_would_notice_changed(tmp_path):
    """The match loop spins while polling for the opponent. Without dedupe this
    file would be rewritten thousands of times per turn."""
    path = tmp_path / "live_state.json"
    publisher = live_state.LiveStatePublisher(path)
    runtime = _FakeRuntime()

    publisher.publish(runtime)
    first = path.stat().st_mtime_ns
    for _ in range(50):
        publisher.publish(runtime)
    assert path.stat().st_mtime_ns == first

    runtime.state.step_number = 2
    publisher.publish(runtime)
    assert live_state.read(path)["step"] == 2


def test_a_publisher_that_cannot_write_never_costs_us_the_game(tmp_path):
    """A viewer must not be able to forfeit a counted series by failing to
    draw a picture."""
    publisher = live_state.LiveStatePublisher(tmp_path / "live_state.json")
    publisher.publish(object())  # nothing like a runtime at all
    assert not (tmp_path / "live_state.json").exists()


def test_the_snapshot_carries_what_the_viewer_needs():
    snapshot = live_state.snapshot_of(_FakeRuntime(), game_id="them-vs-us")
    assert snapshot["grid_size"] == 3
    assert snapshot["own_pos"] == [1, 1]
    assert snapshot["barriers"] == [[0, 2]]
    assert snapshot["belief"][2][2] == 0.75
    assert snapshot["role"] == "police"
    assert snapshot["game_id"] == "them-vs-us"


# --- replay frames --------------------------------------------------------------


def test_the_state_string_is_parsed_into_a_board():
    parsed = replay_frames.parse_state("grid=7x7;self=[1, 0];barriers=[[2, 1], [3, 2]]")
    assert parsed == {"grid_size": 7, "own_pos": [1, 0], "barriers": [[2, 1], [3, 2]]}


@pytest.mark.parametrize("bad", ["", "nonsense", "grid=7x7;self=[1, 0]", "grid=AxB;self=[];barriers=[]"])
def test_an_unparseable_state_string_is_skipped_not_guessed(bad):
    assert replay_frames.parse_state(bad) is None


def test_step_zero_produces_no_frame():
    """It has no position and was never a turn - there is nothing to draw. It
    is still verified by the replay verifier."""
    log = {
        "summary": {"sub_game_number": 1, "role": "police", "result": "survival"},
        "records": [
            {"payload": {"step": 0, "type": "system_spec"}},
            {"payload": {"step": 1, "role": "police", "action_type": "move", "detail": "N",
                         "state": "grid=3x3;self=[0, 0];barriers=[]", "smell_grid": {"1,1": 0.5}}},
        ],
    }
    frames = replay_frames.frames_from_log(log)
    assert len(frames) == 1
    assert frames[0]["step"] == 1
    assert frames[0]["belief"][1][1] == 0.5
    assert frames[0]["heat_label"] == replay_frames.HEAT_LABEL
    assert frames[0]["result"] == "survival", "the last frame carries the outcome"


@pytest.mark.skipif(
    not (REPO_ROOT / "logs" / "log_ali-ahm1-vs-uoh-mh01_g01.json").is_file(),
    reason="the ali-ahm1 artifacts are not in this checkout",
)
def test_the_real_series_renders_every_turn():
    """Against the artifacts of a series that actually happened, rather than a
    fixture written to agree with the code."""
    frames = replay_frames.load_frames(REPO_ROOT / "logs", "ali-ahm1-vs-uoh-mh01", 1)
    assert frames, "no drawable turns"
    assert all(frame["step"] > 0 for frame in frames), "step 0 is not a turn"
    scene = build_scene(frames[-1])
    assert len(scene.cells) == scene.grid_size**2
    assert sum(cell.own for cell in scene.cells) == 1


# --- the PNG writer -------------------------------------------------------------


def test_the_png_writer_emits_a_real_png(tmp_path):
    path = write_png(tmp_path / "out.png", 2, 2, [b"\xff\x00\x00\x00\xff\x00", b"\x00\x00\xff\xff\xff\xff"])
    blob = path.read_bytes()
    assert blob[:8] == b"\x89PNG\r\n\x1a\n"
    width, height = struct.unpack(">2I", blob[16:24])
    assert (width, height) == (2, 2)
    assert blob[24] == 8 and blob[25] == 2, "8-bit truecolour"
    # IEND is 12 bytes: a zero length, the tag, and its fixed CRC.
    assert blob[-12:] == struct.pack(">I", 0) + b"IEND" + struct.pack(">I", 0xAE426082)


def test_the_screenshots_in_the_repo_are_real_pngs():
    """They are the graded artefact, so a zero-byte or truncated file must fail
    here rather than at submission."""
    shots = sorted((REPO_ROOT / "docs" / "screenshots").glob("*.png"))
    assert shots, "no screenshots committed"
    for shot in shots:
        blob = shot.read_bytes()
        assert blob[:8] == b"\x89PNG\r\n\x1a\n", shot.name
        width, height = struct.unpack(">2I", blob[16:24])
        assert width > 200 and height > 200, f"{shot.name} is {width}x{height}"


class _FakeRuntime:
    """Just enough of PeerRuntime for the publisher to read."""

    class _Pos:
        def __init__(self, row, col):
            self.row, self.col = row, col

        def __hash__(self):
            return hash((self.row, self.col))

    class _Board:
        grid_size = 3
        barriers = ()

    class _State:
        step_number = 1

    class _Role:
        value = "police"

    class _PeerConfig:
        group_id = "uoh-mh01"

    def __init__(self):
        self.state = self._State()
        self.state.board = self._Board()
        self.state.board.barriers = (self._Pos(0, 2),)
        self.state.own_pos = self._Pos(1, 1)
        self.role = self._Role()
        self.whose_turn = self._Role()
        self.sub_game_number = 1
        self.peer_config = self._PeerConfig()
        self.outcome = None
        self._belief = {self._Pos(2, 2): 0.75}
