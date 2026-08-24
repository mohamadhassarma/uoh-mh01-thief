"""Saving the viewer window to a PNG.

Book ch.7's checklist is graded from screenshots, so producing them is part of
the deliverable rather than a manual step someone has to remember to redo when
the board changes. Doing it in code also means the picture in the submission is
the picture this code actually draws.

No third-party imaging library: the PNG writer below is the format's own
minimum (one IHDR, one zlib-compressed IDAT of filter-0 scanlines, one IEND),
which is about twenty lines and avoids adding a dependency to a graded project
for one function. Capture itself is Windows GDI via ctypes and returns None
anywhere else, so the caller degrades to "take it yourself" rather than
crashing on a platform this project does not run on.
"""

from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path

PW_RENDERFULLCONTENT = 0x00000002


def write_png(path: Path, width: int, height: int, rgb_rows: list[bytes]) -> Path:
    """`rgb_rows` is one `bytes` of 3*width channels per row, top row first."""
    raw = b"".join(b"\x00" + row for row in rgb_rows)  # filter type 0 per scanline

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    header = struct.pack(">2I5B", width, height, 8, 2, 0, 0, 0)  # 8-bit truecolour
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )
    return path


def grab_window(root) -> tuple[int, int, list[bytes]] | None:
    """Capture a Tk toplevel. Returns (width, height, rgb_rows) or None."""
    if not sys.platform.startswith("win"):
        return None
    import ctypes
    from ctypes import wintypes

    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    root.update()
    hwnd = int(root.wm_frame(), 16)
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    width, height = rect.right - rect.left, rect.bottom - rect.top
    if width <= 0 or height <= 0:
        return None

    window_dc = user32.GetWindowDC(hwnd)
    mem_dc = gdi32.CreateCompatibleDC(window_dc)
    bitmap = gdi32.CreateCompatibleBitmap(window_dc, width, height)
    gdi32.SelectObject(mem_dc, bitmap)
    user32.PrintWindow(hwnd, mem_dc, PW_RENDERFULLCONTENT)

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
            ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
            ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD),
        ]

    info = BITMAPINFOHEADER()
    info.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    info.biWidth, info.biHeight = width, -height  # negative height = top-down rows
    info.biPlanes, info.biBitCount, info.biCompression = 1, 32, 0
    buffer = ctypes.create_string_buffer(width * height * 4)
    gdi32.GetDIBits(mem_dc, bitmap, 0, height, buffer, ctypes.byref(info), 0)

    gdi32.DeleteObject(bitmap)
    gdi32.DeleteDC(mem_dc)
    user32.ReleaseDC(hwnd, window_dc)

    blob = buffer.raw
    rows = []
    for y in range(height):
        line = blob[y * width * 4 : (y + 1) * width * 4]
        # GDI hands back BGRA; PNG truecolour wants RGB.
        rows.append(bytes(b for x in range(width) for b in (line[x * 4 + 2], line[x * 4 + 1], line[x * 4])))
    return width, height, rows


def screenshot(root, path: Path) -> Path | None:
    grabbed = grab_window(root)
    if grabbed is None:
        return None
    width, height, rows = grabbed
    return write_png(Path(path), width, height, rows)
