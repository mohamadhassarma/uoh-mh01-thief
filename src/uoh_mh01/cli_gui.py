"""`gui` - the live board viewer, and the same viewer over a played series.

LIVE mode polls the snapshot the running peer publishes (gui/live_state.py).
It is a separate process on purpose: a viewer must not be able to stall, crash
or forfeit a counted game by being slow to redraw.

REPLAY mode reads a sub-game log and steps through the turns that were really
played. It exists because the live mode can only be screenshotted while a game
happens to be running, and because a finished series is the honest thing to
put in a submission.
"""

from __future__ import annotations

import sys
from pathlib import Path

from .gui.live_state import LIVE_STATE_NAME, read
from .gui.replay_frames import load_frames


class _Cursor:
    """Replay playback state: which frame, and whether it is auto-advancing."""

    def __init__(self, frames: list[dict]) -> None:
        self.frames = frames
        self.index = 0
        self.playing = True

    def current(self) -> dict:
        frame = dict(self.frames[self.index])
        position = f"{self.index + 1}/{len(self.frames)}"
        frame["action"] = f"{frame.get('action', '')}   [{position}]".strip()
        return frame

    def advance(self) -> dict:
        if self.playing and self.index < len(self.frames) - 1:
            self.index += 1
        elif self.playing:
            self.playing = False  # hold on the final frame rather than looping
        return self.current()

    def on_key(self, event) -> None:
        key = getattr(event, "keysym", "")
        if key == "Right":
            self.playing = False
            self.index = min(self.index + 1, len(self.frames) - 1)
        elif key == "Left":
            self.playing = False
            self.index = max(self.index - 1, 0)
        elif key == "Home":
            self.index, self.playing = 0, False
        elif key == "space":
            self.playing = not self.playing


def _save_screenshot(snapshot: dict, path: Path, subtitle: str) -> int:
    """Render one frame and write it to a PNG, with no mainloop.

    The checklist is graded from screenshots, so producing them is part of the
    build rather than a manual step someone has to remember to redo whenever
    the board changes.
    """
    import tkinter as tk

    from .gui.capture import screenshot
    from .gui.tk_app import ViewerWindow

    root = tk.Tk()
    root.title("uoh-mh01 - board viewer")
    window = ViewerWindow(root, grid_size=snapshot.get("grid_size") or 7, subtitle=subtitle)
    window.render(snapshot)
    root.update()
    root.deiconify()
    root.lift()
    root.update()
    written = screenshot(root, path)
    root.destroy()
    if written is None:
        print("screenshot capture is only implemented for Windows; take one by hand", file=sys.stderr)
        return 2
    print(f"wrote {written}")
    return 0


def cmd_gui(args) -> int:
    logs_dir = Path(args.log_dir or "logs")
    from .gui import tk_app  # imported here so a headless box can still import the CLI

    if args.game_id:
        try:
            frames = load_frames(logs_dir, args.game_id, args.sub_game)
        except FileNotFoundError as exc:
            print(f"cannot replay: {exc}", file=sys.stderr)
            return 2
        if not frames:
            print(f"no drawable turns in sub-game {args.sub_game} of {args.game_id}", file=sys.stderr)
            return 2
        if args.screenshot:
            index = min(max(args.frame, 1), len(frames)) - 1
            return _save_screenshot(
                frames[index], Path(args.screenshot), f"REPLAY  -  turn {index + 1} of {len(frames)}"
            )
        cursor = _Cursor(frames)
        tk_app.run(
            cursor.advance,
            grid_size=frames[0]["grid_size"],
            subtitle="REPLAY  -  space: play/pause   left/right: step   home: restart",
            poll_ms=max(args.frame_ms, 30),
            on_key=cursor.on_key,
        )
        return 0

    path = logs_dir / LIVE_STATE_NAME
    first = read(path)
    if args.screenshot:
        if first is None:
            print(f"no live snapshot at {path} yet - start a series first", file=sys.stderr)
            return 2
        return _save_screenshot(first, Path(args.screenshot), "LIVE  -  updates as each turn is sealed")
    print(f"watching {path} - start a series in another terminal; close the window to stop.")
    if first is None:
        print("no live snapshot yet; the window will fill in once a sub-game starts.")
    tk_app.run(
        lambda: read(path),
        grid_size=(first or {}).get("grid_size") or 7,
        subtitle="LIVE  -  updates as each turn is sealed",
    )
    return 0
