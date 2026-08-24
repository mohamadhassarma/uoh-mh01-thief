"""The parts of the viewer that need a display, plus the replay cursor.

Skipped wholesale where no display exists, so this stays green on a headless
box; the drawing DECISIONS are all in `gui/scene.py` and tested unconditionally
in test_gui.py. What is left to check here is that the painter paints what the
scene told it to, and that the playback controls behave.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from uoh_mh01.cli_gui import _Cursor

REPO_ROOT = Path(__file__).resolve().parents[1]


def _has_display() -> bool:
    try:
        import tkinter as tk

        tk.Tk().destroy()
        return True
    except Exception:  # noqa: BLE001 - any failure here means "no display"
        return False


needs_display = pytest.mark.skipif(not _has_display(), reason="no display available")


def _snapshot(**overrides):
    base = {
        "grid_size": 3,
        "role": "police",
        "sub_game_number": 1,
        "step": 4,
        "whose_turn": "police",
        "own_pos": [0, 0],
        "barriers": [[1, 1]],
        "belief": [[0.0, 0.1, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.4]],
        "game_id": "them-vs-us",
        "result": None,
    }
    return {**base, **overrides}


# --- replay playback controls (no display needed) -------------------------------


def _frames(n: int):
    return [_snapshot(step=i, action=f"move {i}") for i in range(1, n + 1)]


def test_playback_advances_one_frame_at_a_time():
    cursor = _Cursor(_frames(3))
    assert cursor.current()["step"] == 1
    assert cursor.advance()["step"] == 2
    assert cursor.advance()["step"] == 3


def test_playback_holds_on_the_last_frame_rather_than_looping():
    """A viewer that snapped back to turn 1 the moment the game ended would be
    impossible to screenshot at its most interesting point."""
    cursor = _Cursor(_frames(2))
    cursor.advance()
    for _ in range(5):
        assert cursor.advance()["step"] == 2
    assert not cursor.playing


def test_the_position_counter_is_shown_so_the_reader_knows_where_they_are():
    cursor = _Cursor(_frames(4))
    assert "[1/4]" in cursor.current()["action"]
    cursor.advance()
    assert "[2/4]" in cursor.current()["action"]


def test_the_arrow_keys_step_and_pause():
    cursor = _Cursor(_frames(4))
    cursor.on_key(_Key("Right"))
    assert cursor.index == 1
    assert not cursor.playing, "stepping by hand must stop autoplay"
    cursor.on_key(_Key("Left"))
    assert cursor.index == 0


def test_stepping_cannot_run_off_either_end():
    cursor = _Cursor(_frames(2))
    for _ in range(5):
        cursor.on_key(_Key("Left"))
    assert cursor.index == 0
    for _ in range(5):
        cursor.on_key(_Key("Right"))
    assert cursor.index == 1


def test_space_toggles_play_and_home_restarts():
    cursor = _Cursor(_frames(3))
    cursor.on_key(_Key("space"))
    assert not cursor.playing
    cursor.on_key(_Key("space"))
    assert cursor.playing
    cursor.advance()
    cursor.on_key(_Key("Home"))
    assert cursor.index == 0 and not cursor.playing


def test_an_unknown_key_does_nothing():
    cursor = _Cursor(_frames(3))
    cursor.on_key(_Key("q"))
    assert cursor.index == 0 and cursor.playing


class _Key:
    def __init__(self, keysym):
        self.keysym = keysym


# --- the painter ----------------------------------------------------------------


@pytest.fixture(scope="module")
def tk_root():
    """ONE Tk interpreter for the whole module.

    Creating and destroying a root per test exhausts something in Tk on
    Windows and blows up partway through with a TclError out of
    `ttk::LoadThemes` - which looks exactly like a bug in the code under test
    and is not one.
    """
    import tkinter as tk

    root = tk.Tk()
    root.withdraw()
    yield root
    root.destroy()


@needs_display
class TestTheWindow:
    @pytest.fixture
    def window(self, tk_root):
        import tkinter as tk

        from uoh_mh01.gui.tk_app import ViewerWindow

        top = tk.Toplevel(tk_root)
        yield top, ViewerWindow(top, grid_size=3, subtitle="TEST")
        top.destroy()

    def test_every_cell_is_drawn(self, window):
        _, view = window
        view.render(_snapshot())
        rectangles = [i for i in view.canvas.find_all() if view.canvas.type(i) == "rectangle"]
        # 9 cells, plus the outline on the peak cell.
        assert len(rectangles) == 10

    def test_the_cell_colours_come_from_the_scene_not_the_painter(self, window):
        """The painter must not compute a colour of its own - that decision has
        to stay where it can be tested without a display."""
        from uoh_mh01.gui.scene import BARRIER, build_scene

        _, view = window
        snapshot = _snapshot()
        view.render(snapshot)
        painted = {
            view.canvas.itemcget(i, "fill")
            for i in view.canvas.find_all()
            if view.canvas.type(i) == "rectangle" and view.canvas.itemcget(i, "fill")
        }
        expected = {cell.fill for cell in build_scene(snapshot).cells}
        assert expected <= painted
        assert BARRIER in painted

    def test_own_position_is_drawn_as_a_marker(self, window):
        _, view = window
        view.render(_snapshot())
        assert [i for i in view.canvas.find_all() if view.canvas.type(i) == "oval"]

    def test_the_hud_reports_the_sub_game_role_and_turn(self, window):
        _, view = window
        view.render(_snapshot(sub_game_number=4, whose_turn="thief"))
        text = view.hud.cget("text")
        assert "sub-game" in text and "4" in text
        assert "police" in text
        assert "waiting for opponent" in text

    def test_rendering_twice_does_not_pile_up_canvas_items(self, window):
        """`after()` redraws several times a second for the whole series."""
        _, view = window
        view.render(_snapshot())
        first = len(view.canvas.find_all())
        for step in range(2, 12):
            view.render(_snapshot(step=step))
        assert len(view.canvas.find_all()) == first

    def test_a_board_of_a_different_size_still_paints_fully(self, window):
        _, view = window
        view.render(_snapshot(grid_size=7, belief=[[0.0] * 7 for _ in range(7)], barriers=[]))
        cells = [i for i in view.canvas.find_all() if view.canvas.type(i) == "rectangle"]
        assert len(cells) == 49


# --- screenshots ----------------------------------------------------------------


@needs_display
def test_the_screenshot_flag_writes_a_real_png(tmp_path):
    """The graded artefact. Generating it in code means the picture in the
    submission is the picture this code actually draws."""
    from uoh_mh01.cli_gui import _save_screenshot

    out = tmp_path / "shot.png"
    assert _save_screenshot(_snapshot(), out, "TEST") == 0
    blob = out.read_bytes()
    assert blob[:8] == b"\x89PNG\r\n\x1a\n"
    width, height = struct.unpack(">2I", blob[16:24])
    assert width > 200 and height > 200


@needs_display
def test_the_replay_screenshot_renders_a_chosen_turn(tmp_path):
    from uoh_mh01.__main__ import main

    logs = REPO_ROOT / "logs"
    if not (logs / "log_ali-ahm1-vs-uoh-mh01_g01.json").is_file():
        pytest.skip("the ali-ahm1 artifacts are not in this checkout")
    out = tmp_path / "replay.png"
    code = main([
        "gui", "--game-id", "ali-ahm1-vs-uoh-mh01", "--sub-game", "1",
        "--frame", "5", "--screenshot", str(out), "--log-dir", str(logs),
    ])
    assert code == 0
    assert out.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


# --- the command's refusals -----------------------------------------------------


def test_replaying_a_series_that_is_not_there_is_reported_cleanly(tmp_path, capsys):
    from uoh_mh01.__main__ import main

    code = main(["gui", "--game-id", "no-such-game", "--log-dir", str(tmp_path)])
    assert code == 2
    assert "cannot replay" in capsys.readouterr().err


def test_screenshotting_a_live_game_that_has_not_started_says_so(tmp_path, capsys):
    from uoh_mh01.__main__ import main

    code = main(["gui", "--log-dir", str(tmp_path), "--screenshot", str(tmp_path / "x.png")])
    assert code == 2
    assert "no live snapshot" in capsys.readouterr().err


def test_a_sub_game_with_no_drawable_turns_is_reported(tmp_path, capsys):
    import json

    from uoh_mh01.__main__ import main

    (tmp_path / "log_g-vs-h_g01.json").write_text(
        json.dumps({"summary": {"sub_game_number": 1}, "records": [{"payload": {"step": 0}}]}), encoding="utf-8"
    )
    code = main(["gui", "--game-id", "g-vs-h", "--log-dir", str(tmp_path)])
    assert code == 2
    assert "no drawable turns" in capsys.readouterr().err
