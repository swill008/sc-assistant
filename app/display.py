"""Monitor geometry for the scanner.

Which monitor the game is on, what its real resolution and scaling are, and
how to keep the calibrated box on the signature when that monitor changes.

Everything here is physical pixels (what mss captures). Qt's logical
coordinates are per-monitor and differ between monitors with different
Windows scaling, so they are only used to find the physical rects.
"""
from __future__ import annotations

from PySide6.QtGui import QGuiApplication

from . import win32


def physical_rect(screen) -> dict:
    """Physical-pixel rect of a Qt screen, matched against the OS monitors."""
    geo = screen.geometry()
    dpr = float(screen.devicePixelRatio() or 1.0)
    width, height = round(geo.width() * dpr), round(geo.height() * dpr)
    same_size = [m for m in win32.monitors()
                 if abs(m["width"] - width) <= 2 and abs(m["height"] - height) <= 2]
    for mon in same_size:
        if mon["left"] == geo.x() and mon["top"] == geo.y():
            return {k: mon[k] for k in ("left", "top", "width", "height")}
    if len(same_size) == 1:
        return {k: same_size[0][k] for k in ("left", "top", "width", "height")}
    return {"left": round(geo.x() * dpr), "top": round(geo.y() * dpr),
            "width": width, "height": height}


def screen_label(screen) -> str:
    """``LG ULTRAGEAR+ · 5120×2160 · 150%`` for the monitor list."""
    rect = physical_rect(screen)
    scale = round(float(screen.devicePixelRatio() or 1.0) * 100)
    return f"{screen.name()} · {rect['width']}×{rect['height']} · {scale}%"


def monitor_choices() -> list[tuple[str, str]]:
    """(screen name, label) for every connected monitor, primary first."""
    primary = QGuiApplication.primaryScreen()
    screens = sorted(QGuiApplication.screens(), key=lambda s: s is not primary)
    return [(s.name(), screen_label(s)) for s in screens]


def find_screen(name: str | None):
    """The connected Qt screen with this name, or None."""
    for screen in QGuiApplication.screens():
        if screen.name() == name:
            return screen
    return None


def screen_of_region(region: dict | None):
    """The Qt screen whose physical rect contains the box's centre."""
    if not region:
        return None
    cx = region["left"] + region["width"] / 2
    cy = region["top"] + region["height"] / 2
    for screen in QGuiApplication.screens():
        r = physical_rect(screen)
        if r["left"] <= cx < r["left"] + r["width"] and r["top"] <= cy < r["top"] + r["height"]:
            return screen
    return None


def logical_geometry(rect: dict, screen):
    """QRect in Qt's logical coordinates for a physical rect on ``screen``."""
    from PySide6.QtCore import QRect

    phys = physical_rect(screen)
    geo = screen.geometry()
    dpr = float(screen.devicePixelRatio() or 1.0)
    return QRect(geo.x() + round((rect["left"] - phys["left"]) / dpr),
                 geo.y() + round((rect["top"] - phys["top"]) / dpr),
                 max(1, round(rect["width"] / dpr)),
                 max(1, round(rect["height"] / dpr)))


def same_rect(a: dict | None, b: dict | None) -> bool:
    keys = ("left", "top", "width", "height")
    return bool(a and b) and all(int(a[k]) == int(b[k]) for k in keys)


def rescale(region: dict, old: dict, new: dict) -> dict:
    """Move a box from one monitor rect to another.

    Star Citizen scales its HUD with the vertical resolution and keeps it
    centred, so the box keeps its offset from the monitor centre and both
    are scaled by the height ratio. For the same aspect ratio this is plain
    proportional scaling; for a different aspect ratio (21:9 to 16:9) the
    HUD does not stretch sideways, and neither does the box.
    """
    k = new["height"] / old["height"]
    old_cx = old["left"] + old["width"] / 2
    old_cy = old["top"] + old["height"] / 2
    new_cx = new["left"] + new["width"] / 2
    new_cy = new["top"] + new["height"] / 2
    return {
        "left": round(new_cx + (region["left"] - old_cx) * k),
        "top": round(new_cy + (region["top"] - old_cy) * k),
        "width": max(1, round(region["width"] * k)),
        "height": max(1, round(region["height"] * k)),
    }
