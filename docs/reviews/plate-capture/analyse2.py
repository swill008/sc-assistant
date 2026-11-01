"""Analysis only: baseline (today's find_anchor with a digits box) vs whole-plate box,
and a digits strip measured from the pin's right edge."""
import json, sys
from pathlib import Path
from collections import Counter
import cv2, numpy as np
ROOT = Path(r"E:\Users\Stacie\Documents\GitHub\citizen-assistant")
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(Path(__file__).parent))
from app import tracking
from app.ocr import SignatureOCR
from analyse import find_pin_in_box, VARIANTS, lab, FIX

ocr = SignatureOCR(2000, 100000)
def read(img, r):
    x, y, w, h = r
    return ocr.read(img[max(0,y):y+h, max(0,x):x+w]).value

def strip_from_pin(pin, box):
    px, py, pw, ph = pin
    x0 = px + pw + 2
    x1 = min(box[0] + box[2], x0 + int(5 * ph))
    return (x0, py - 3, max(1, x1 - x0), ph + 6)

base, newA, newB = Counter(), Counter(), Counter()
bad = []
for fr in lab["frames"]:
    if fr["pin"] is None:
        continue
    img = cv2.imread(str(FIX / fr["file"]))
    px, py = fr["pin"]
    # today: the user draws the digits box (true digits: 33 px right of the pin, 57x25 like the calibration)
    digits_box = (px + 33, py + 1, 57, 25)
    a = tracking.find_anchor(img, digits_box)
    if a is None:
        base["no pin"] += 1; bad.append((fr["file"], "today", "no pin"))
    else:
        tx, ty = int(round(px - tracking.PIN_MARGIN)), int(round(py - tracking.PIN_MARGIN))
        got = read(img, (tx + a.digits[0], ty + a.digits[1], a.digits[2], a.digits[3]))
        base["ok" if got == fr["value"] else "misread"] += 1
        if got != fr["value"]: bad.append((fr["file"], "today", got))
    for name, (ox, oy, w, h) in VARIANTS.items():
        box = (px + ox, py + oy, w, h)
        pin, why = find_pin_in_box(img, box)
        if pin is None:
            newB[name, "missed"] += 1; continue
        got = read(img, strip_from_pin(pin, box))
        k = "ok" if got == fr["value"] else "misread"
        newB[name, k] += 1
        if k != "ok": bad.append((fr["file"], name, got))
print("today (digits box, find_anchor):", dict(base))
for name in VARIANTS:
    print(f"plate box + strip from pin, {name:36}", {k[1]: v for k, v in newB.items() if k[0] == name})
print()
for b in bad: print(b)
