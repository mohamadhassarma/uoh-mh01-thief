"""`replay` - re-verify a played series straight off its JSON artifacts.

Book ch.7 makes a replay viewer a submission requirement, and this is the half
that carries the proof: every sealed record is re-hashed with SHA-256 and
compared against the commit stored beside it, and the series is declared
`Verified OK` or `TAMPERED`.

Output is deliberately plain ASCII in a fixed-width table. It is graded from a
screenshot, and the console this runs on is cp1255 - a box-drawing character or
a section sign here crashes the command before it prints anything (which has
already happened once in this project, in the report CLI).
"""

from __future__ import annotations

import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

from .replay.verify import VERDICT_OK, SeriesVerdict, verify_series
from .report.series_reader import SeriesNotFoundError

RULE = "=" * 78


def _header(verdict: SeriesVerdict, logs_dir: Path) -> None:
    print(RULE)
    print(f"  REPLAY VERIFICATION - {verdict.game_id}")
    print(f"  game_uid   {verdict.game_uid}")
    print(f"  artifacts  {logs_dir.resolve()}")
    print(RULE)


def _table(verdict: SeriesVerdict) -> None:
    print("  sub-game  role    result            records  step-0  re-hashed  verdict")
    print("  --------  ------  ----------------  -------  ------  ---------  -----------")
    for sub in verdict.sub_games:
        print(
            f"  {sub.sub_game_number:<8}  {sub.role:<6}  {(sub.result or '-')[:16]:<16}"
            f"  {sub.records:>7}  {'yes' if sub.step_zero_present else 'no':<6}"
            f"  {sub.audit.verified_steps:>9}  {sub.verdict}"
        )
        if not sub.ok:
            print(f"            reason: {sub.audit.reason}")
            if sub.audit.failed_steps:
                print(f"            failed steps: {list(sub.audit.failed_steps)}")


def _footer(verdict: SeriesVerdict) -> None:
    print(RULE)
    print(f"  SERIES VERDICT: {verdict.verdict}")
    print(f"  {len(verdict.sub_games)} sub-games, {verdict.verified_steps} sealed steps re-hashed (SHA-256).")
    print("  Step-0 host-spec records are verified self-consistently and excluded from")
    print("  the played-step count: disclosure-only, never transmitted as a turn.")
    if verdict.ok:
        print("  Every record still re-hashes to the commit stored beside it - the")
        print("  artifacts have not been edited since they were written.")
    else:
        print("  At least one record no longer re-hashes to its stored commit.")
    print(RULE)


def _render_png(text: str, path: Path) -> int:
    """Draw this command's own output into a PNG.

    It is a rendering of the text the command really printed - captured from
    stdout, not retyped - so the submission holds a picture of what the tool
    actually says. Screenshotting the terminal by hand does the same job; this
    just makes it reproducible when the output changes.
    """
    import tkinter as tk

    from .gui.capture import screenshot
    from .gui.scene import BACKGROUND, TEXT

    root = tk.Tk()
    root.title("uoh-mh01 - replay verification")
    root.configure(bg=BACKGROUND)
    tk.Label(
        root, text=text.rstrip(), font=("Consolas", 11), fg=TEXT, bg=BACKGROUND, justify="left", anchor="w"
    ).pack(padx=18, pady=14, anchor="w")
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


def cmd_replay(args) -> int:
    logs_dir = Path(args.log_dir or "logs")
    try:
        verdict = verify_series(logs_dir, args.game_id)
    except SeriesNotFoundError as exc:
        print(f"cannot replay: {exc}", file=sys.stderr)
        return 2

    buffer = io.StringIO()
    with redirect_stdout(buffer):
        _header(verdict, logs_dir)
        _table(verdict)
        _footer(verdict)
    report = buffer.getvalue()
    print(report, end="")

    if getattr(args, "screenshot", None):
        _render_png(report, Path(args.screenshot))
    # Non-zero on TAMPERED so this is usable as a check, not just a display.
    return 0 if verdict.verdict == VERDICT_OK else 1
