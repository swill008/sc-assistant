"""Follow the signature plate as the HUD sways.

The plate's orange location-pin icon is the anchor: calibration cuts it out of
the screen next to the user's digits box, and each scan finds it again in a
larger search area and reads the digits at a fixed offset from it.

Search is coarse-to-fine: a quarter-size "orangeness" (R - B) map finds a few
candidates, then full-resolution colour matching in a small window around each
gives the score. White text, grey terrain and the blue-ish sky are ~0 in R - B,
so the coarse map ignores most of the frame.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

PIN_MARGIN = 2          # px kept around the pin in the template

# Plate geometry at 5K2K, in pin heights (pin 24x28): digits start 33 px right
# of the pin's left edge, 1 px above its top, same height.
_PIN_W = 24 / 28
_DIGITS_X = 33 / 28
_DIGITS_SLACK = 3
_DIGITS_W = 3.2         # room for up to 6 digits + comma
_DIGITS_W_MAX = 5.0
_LEVELS = 2             # coarse search at 1/2**_LEVELS size
_COARSE_PEAKS = 5       # coarse candidates refined at full resolution (tinted or
                        # blurred frames put the pin 3rd-4th on the coarse map)


@dataclass
class Anchor:
    template: np.ndarray                    # BGR pin icon incl. PIN_MARGIN
    digits: tuple[int, int, int, int]       # (dx, dy, w, h) from the template's top-left
    _coarse: np.ndarray = field(init=False, repr=False, compare=False)

    def __post_init__(self):
        self._coarse = _orange(_shrink(self.template))

    def save(self, folder: Path) -> dict:
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        # imencode + tofile: cv2.imwrite can't write non-ASCII paths on Windows
        ok, buf = cv2.imencode(".png", self.template)
        if not ok:
            raise OSError("could not encode the anchor image")
        buf.tofile(str(folder / "anchor.png"))
        return {"file": "anchor.png", "digits": [int(v) for v in self.digits]}

    @classmethod
    def load(cls, folder: Path, meta: dict) -> Anchor | None:
        try:
            path = Path(folder) / str(meta["file"])
            digits = tuple(int(v) for v in meta["digits"])
            if len(digits) != 4 or digits[2] <= 0 or digits[3] <= 0:
                return None
            # imdecode: cv2.imread can't open non-ASCII paths on Windows
            data = np.fromfile(str(path), dtype=np.uint8)
            img = cv2.imdecode(data, cv2.IMREAD_COLOR)
        except (KeyError, TypeError, ValueError, OSError):
            return None
        if img is None or img.shape[0] < 8 or img.shape[1] < 8:
            return None
        return cls(img, digits)


@dataclass
class Match:
    x: int                  # template top-left in the searched image
    y: int
    score: float            # 0..1, TM_CCOEFF_NORMED at full resolution


def _shrink(img: np.ndarray) -> np.ndarray:
    # pyrDown: ~4x faster than resize(INTER_AREA) on a 1060x830 frame
    for _ in range(_LEVELS):
        img = cv2.pyrDown(img)
    return img


def _orange(bgr: np.ndarray) -> np.ndarray:
    """R - B, saturating: orange is high, white/grey/blue ~0."""
    b, _, r = cv2.split(bgr)
    return cv2.subtract(r, b)


def find_anchor(image: np.ndarray, digits: tuple[int, int, int, int]) -> Anchor | None:
    """Cut the pin icon out of the strip just left of the digits box."""
    bx, by, bw, bh = (int(v) for v in digits)
    if bh < 8 or image is None or image.ndim != 3:
        return None
    ih, iw = image.shape[:2]
    # strip: up to 3 box heights left of the box, half a height above/below
    x0, x1 = max(0, bx - 3 * bh), min(iw, bx + bh // 2)
    y0, y1 = max(0, by - bh // 2), min(ih, by + bh + bh // 2)
    if x1 - x0 < bh or y1 - y0 < bh:
        return None
    ob = _orange(image[y0:y1, x0:x1]).astype(np.float32)
    # the pin is the most orange thing there; the plate behind it is dimmer
    peak = float(np.percentile(ob, 99.5))
    if peak < 60:
        return None
    mask = (ob >= 0.75 * peak).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    # columns that carry the pin; the run nearest the box (gaps <= 2 px allowed)
    cols = np.flatnonzero(mask.sum(axis=0) >= 2)
    if cols.size == 0:
        return None
    runs, start = [], cols[0]
    for a, b in zip(cols[:-1], cols[1:]):
        if b - a > 3:
            runs.append((start, a))
            start = b
    runs.append((start, cols[-1]))
    c0, c1 = runs[-1]
    rows = np.flatnonzero(mask[:, c0:c1 + 1].sum(axis=1) >= 1)
    r0, r1 = int(rows[0]), int(rows[-1])
    ph = r1 - r0 + 1
    # sanity: a pin is about box-high and a bit narrower than tall
    if not (0.6 * bh <= ph <= 1.8 * bh and 0.5 * ph <= c1 - c0 + 1 <= 1.2 * ph):
        return None
    # The template is the bright part only: the base's dim ends sit on the
    # see-through plate and match worse than they help. The icon's true left
    # edge (for the digits offset) comes from its height, centred on the run.
    py = y0 + r0
    tx, ty = x0 + c0 - PIN_MARGIN, py - PIN_MARGIN
    tx1, ty1 = x0 + c1 + 1 + PIN_MARGIN, py + ph + PIN_MARGIN
    if tx < 0 or ty < 0 or tx1 > iw or ty1 > ih:
        return None
    template = image[ty:ty1, tx:tx1].copy()
    px = x0 + (c0 + c1 + 1 - _PIN_W * ph) / 2
    # start a few px early (into the gap after the pin) so a sway-blurred
    # first digit isn't clipped
    dx = round(px - tx + _DIGITS_X * ph) - _DIGITS_SLACK
    dy = PIN_MARGIN - 1
    w = round(_DIGITS_W * ph)
    # cover the user's box too, within reason
    w = max(w, bx + bw - (tx + dx))
    w = int(min(w, round(_DIGITS_W_MAX * ph)))
    return Anchor(template, (int(dx), int(dy), w, int(ph) + 2))


def locate(image: np.ndarray, anchor: Anchor, min_score: float = 0.6) -> Match | None:
    """Find the pin in `image`; None when nothing scores >= min_score.

    0.6: on a 300-frame flight every match from 0.55 up was a real plate
    (tinted/blurred ones score 0.55-0.7); frames with no plate scored <= 0.34.
    """
    tpl = anchor.template
    th, tw = tpl.shape[:2]
    ih, iw = image.shape[:2]
    if ih < th or iw < tw:
        return None
    small = _orange(_shrink(image))
    ct = anchor._coarse
    if small.shape[0] < ct.shape[0] or small.shape[1] < ct.shape[1]:
        return None
    res = cv2.matchTemplate(small, ct, cv2.TM_CCOEFF_NORMED)
    best: Match | None = None
    sup_w, sup_h = max(2, ct.shape[1] // 2), max(2, ct.shape[0] // 2)
    for _ in range(_COARSE_PEAKS):
        _, cscore, _, (cx, cy) = cv2.minMaxLoc(res)
        if cscore <= 0.0:
            break
        res[max(0, cy - sup_h):cy + sup_h + 1, max(0, cx - sup_w):cx + sup_w + 1] = -1
        # refine in colour at full resolution
        s = 1 << _LEVELS
        fx0, fy0 = max(0, s * cx - s - 1), max(0, s * cy - s - 1)
        fx1, fy1 = min(iw, s * cx + s + tw + 2), min(ih, s * cy + s + th + 2)
        win = image[fy0:fy1, fx0:fx1]
        if win.shape[0] < th or win.shape[1] < tw:
            continue
        r = cv2.matchTemplate(win, tpl, cv2.TM_CCOEFF_NORMED)
        _, score, _, (lx, ly) = cv2.minMaxLoc(r)
        if best is None or score > best.score:
            best = Match(fx0 + lx, fy0 + ly, float(score))
    if best is None or best.score < min_score:
        return None
    return best


def digits_rect(match: Match, anchor: Anchor) -> tuple[int, int, int, int]:
    dx, dy, w, h = anchor.digits
    return match.x + dx, match.y + dy, w, h


def search_area(region: dict, range_x: int, range_y: int) -> dict:
    """The digits box grown by range_x/range_y each side, plus room for the pin
    on the left and for the pin being a little taller than the box."""
    h = int(region["height"])
    pin_room = 2 * h
    pad = h // 2
    return {
        "left": int(region["left"]) - range_x - pin_room,
        "top": int(region["top"]) - range_y - pad,
        "width": int(region["width"]) + 2 * range_x + pin_room,
        "height": h + 2 * range_y + 2 * pad,
    }
