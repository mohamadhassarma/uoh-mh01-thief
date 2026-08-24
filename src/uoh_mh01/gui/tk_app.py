"""The Tk viewer window: board, own position, barriers, heatmap, HUD.

A thin painter over `scene.py`. It decides pixel geometry and nothing else -
every colour and every label is computed in `scene.py`, where it can be tested
without a display. Tk is imported lazily by `cli_gui.py` so that importing this
package on a headless box does not fail.
"""

from __future__ import annotations

import tkinter as tk
from typing import Any

from .scene import BACKGROUND, GRID_LINE, OWN_POLICE, OWN_THIEF, TEXT, TEXT_DIM, Scene, build_scene

CELL = 58
MARGIN = 18
PANEL_WIDTH = 330


class ViewerWindow:
    """One window. `render(snapshot)` is the whole interface."""

    def __init__(self, root: tk.Misc, *, grid_size: int, subtitle: str = "") -> None:
        self.root = root
        board_px = grid_size * CELL + 2 * MARGIN
        root.configure(bg=BACKGROUND)
        self.canvas = tk.Canvas(
            root, width=board_px, height=board_px, bg=BACKGROUND, highlightthickness=0, bd=0
        )
        self.canvas.grid(row=0, column=0, rowspan=2, padx=12, pady=12)

        self.panel = tk.Frame(root, bg=BACKGROUND)
        self.panel.grid(row=0, column=1, sticky="nw", padx=(0, 16), pady=18)
        self.title = tk.Label(self.panel, text="", fg=TEXT, bg=BACKGROUND, font=("Consolas", 13, "bold"))
        self.title.pack(anchor="w")
        self.subtitle = tk.Label(self.panel, text=subtitle, fg=TEXT_DIM, bg=BACKGROUND, font=("Consolas", 9))
        self.subtitle.pack(anchor="w", pady=(0, 10))
        self.hud = tk.Label(
            self.panel, text="", fg=TEXT, bg=BACKGROUND, font=("Consolas", 11), justify="left", anchor="w"
        )
        self.hud.pack(anchor="w")
        self.legend = tk.Frame(self.panel, bg=BACKGROUND)
        self.legend.pack(anchor="w", pady=(14, 0))
        self.footer = tk.Label(
            root, text="", fg=TEXT_DIM, bg=BACKGROUND, font=("Consolas", 9), wraplength=board_px + PANEL_WIDTH
        )
        self.footer.grid(row=2, column=0, columnspan=2, sticky="w", padx=14, pady=(0, 10))
        self._legend_drawn = False

    def render(self, snapshot: dict[str, Any]) -> None:
        scene = build_scene(snapshot)
        self._paint_board(scene, snapshot.get("role", "police"))
        self.title.configure(text=scene.title or "uoh-mh01")
        self.hud.configure(text="\n".join(f"{name:<15} {value}" for name, value in scene.hud))
        self.footer.configure(text=scene.footer)
        if not self._legend_drawn:
            self._draw_legend(scene)
            self._legend_drawn = True

    def _paint_board(self, scene: Scene, role: str) -> None:
        self.canvas.delete("all")
        own_colour = OWN_POLICE if role == "police" else OWN_THIEF
        for cell in scene.cells:
            x0 = MARGIN + cell.col * CELL
            y0 = MARGIN + cell.row * CELL
            self.canvas.create_rectangle(
                x0, y0, x0 + CELL, y0 + CELL, fill=cell.fill, outline=GRID_LINE, width=1
            )
            if cell.peak:
                # The single most-suspected cell, outlined so it survives being
                # printed or screenshotted in greyscale.
                self.canvas.create_rectangle(
                    x0 + 3, y0 + 3, x0 + CELL - 3, y0 + CELL - 3, outline="#ff9a94", width=2
                )
            if cell.barrier:
                self.canvas.create_line(x0, y0, x0 + CELL, y0 + CELL, fill="#2a2a36", width=2)
                self.canvas.create_line(x0 + CELL, y0, x0, y0 + CELL, fill="#2a2a36", width=2)
            if cell.own:
                pad = 12
                self.canvas.create_oval(
                    x0 + pad, y0 + pad, x0 + CELL - pad, y0 + CELL - pad, fill=own_colour, outline=""
                )

    def _draw_legend(self, scene: Scene) -> None:
        for label, colour in scene.legend:
            row = tk.Frame(self.legend, bg=BACKGROUND)
            row.pack(anchor="w")
            tk.Canvas(row, width=14, height=14, bg=colour, highlightthickness=0).pack(side="left")
            tk.Label(row, text=f" {label}", fg=TEXT_DIM, bg=BACKGROUND, font=("Consolas", 9)).pack(side="left")


def run(source, *, grid_size: int, subtitle: str, poll_ms: int = 250, on_key=None) -> None:
    """Open the window and pump `source()` for snapshots until it is closed."""
    root = tk.Tk()
    root.title("uoh-mh01 - live viewer")
    window = ViewerWindow(root, grid_size=grid_size, subtitle=subtitle)
    if on_key is not None:
        root.bind("<Key>", on_key)

    def tick() -> None:
        snapshot = source()
        if snapshot is not None:
            window.render(snapshot)
        root.after(poll_ms, tick)

    tick()
    root.mainloop()
