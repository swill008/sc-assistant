"""Analysis only: can the pin + digits be found inside a whole-plate box?"""
import json, sys
from pathlib import Path
import cv2, numpy as np
ROOT = Path(r"E:\Users\Stacie\Documents\GitHub\citizen-assistant")
sys.path.insert(0, str(ROOT))
from app import tracking
from app.ocr import SignatureOCR

FIX = ROOT / "tools/fixtures/hud_track"
lab = json.loads((FIX / "labels.json").read_text(encoding="utf-8"))
SCREEN_H = 2160
PIN_H = 28 * SCREEN_H / 2160        # expected pin height at this screen height

def find_pin_in_box(img, box):
    x, y, w, h = box
    ih, iw = img.shape[:2]
    x0, y0, x1, y1 = max(0, x), max(0, y), min(iw, x + w), min(ih, y + h)
    sub = img[y0:y1, x0:x1]
    ob = tracking._orange(sub).astype(np.float32)
    peak = float(np.percentile(ob, 99.5))
    if peak < 60:
        return None, "no orange"
    mask = (ob >= 0.75 * peak).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    cands = []
    for i in range(1, n):
        cx, cy, cw, ch, area = stats[i]
        if not (0.6 * PIN_H <= ch <= 1.6 * PIN_H):
            continue
        if not (0.45 * ch <= cw <= 1.2 * ch):
            continue
        if area < 0.25 * cw * ch:
            continue
        cands.append((cx + x0, cy + y0, cw, ch))
    if not cands:
        return None, "no pin-shaped mark"
    cands.sort(key=lambda c: c[0])      # left-most
    return cands[0], f"{len(cands)} candidate(s)"

def digits_from_pin(pin):
    px, py, pw, ph = pin
    left = px + pw / 2 - tracking._PIN_W * ph / 2
    dx = left + tracking._DIGITS_X * ph - tracking._DIGITS_SLACK
    return (int(round(dx)), py - 1, int(round(tracking._DIGITS_W * ph)), ph + 2)

ocr = SignatureOCR(2000, 100000)
VARIANTS = {   # box around the plate, relative to the labelled pin top-left (24x28)
    "tight":      (-12, -8, 150, 44),
    "loose":      (-35, -25, 195, 80),
    "very loose (incl. compass ticks)": (-70, -40, 260, 150),
    "shifted right (pin near left edge)": (-4, -6, 150, 40),
}
rows = []
for fr in lab["frames"]:
    img = cv2.imread(str(FIX / fr["file"]))
    for name, (ox, oy, w, h) in VARIANTS.items():
        if fr["pin"] is None:
            # no plate: draw the box at the calibrated spot; must find nothing usable
            box = (500 + ox, 400 + oy, w, h)
            pin, why = find_pin_in_box(img, box)
            rows.append((fr["file"], name, None, "FALSE PIN" if pin else "ok: none", why, None))
            continue
        px, py = fr["pin"]
        box = (px + ox, py + oy, w, h)
        pin, why = find_pin_in_box(img, box)
        if pin is None:
            rows.append((fr["file"], name, fr["value"], "MISSED", why, None)); continue
        err = max(abs(pin[0] - px), abs(pin[1] - py))
        dx, dy, dw, dh = digits_from_pin(pin)
        res = ocr.read(img[dy:dy + dh, dx:dx + dw])
        got = res.value
        verdict = "ok" if err <= 4 and got == fr["value"] else ("PIN OFF" if err > 4 else "READ " + str(got))
        rows.append((fr["file"], name, fr["value"], verdict, f"{why}, pin err {err}px", got))

from collections import Counter
for name in VARIANTS:
    c = Counter(r[3] if not r[3].startswith("READ") else "misread" for r in rows if r[1] == name)
    print(f"{name:38} {dict(c)}")
print()
for r in rows:
    if not r[3].startswith("ok"):
        print(r)
