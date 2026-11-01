"""Analysis only: find the pin inside the drawn plate box by matching the reference pin."""
import json, sys
from pathlib import Path
from collections import Counter
import cv2
ROOT = Path(r"E:\Users\Stacie\Documents\GitHub\citizen-assistant")
sys.path.insert(0, str(ROOT))
from app import tracking
from app.ocr import SignatureOCR
FIX = ROOT / "tools/fixtures/hud_track"
lab = json.loads((FIX / "labels.json").read_text(encoding="utf-8"))
ref = cv2.imread(str(ROOT / "tools/fixtures/signal_42000_5k2k.png"))
REF = tracking.find_anchor(ref, (76, 38, 56, 28))
assert REF is not None
ocr = SignatureOCR(2000, 100000)
VARIANTS = {"tight": (-12, -8, 150, 44), "loose": (-35, -25, 195, 80),
            "very loose (incl. compass ticks)": (-70, -40, 260, 150),
            "pin at left edge": (-4, -6, 150, 40)}
res = Counter(); bad = []
for fr in lab["frames"]:
    img = cv2.imread(str(FIX / fr["file"]))
    for name, (ox, oy, w, h) in VARIANTS.items():
        bx, by = (500, 400) if fr["pin"] is None else fr["pin"]
        x, y = max(0, bx + ox), max(0, by + oy)
        sub = img[y:y + h, x:x + w]
        m = tracking.locate(sub, REF)
        if fr["pin"] is None:
            k = "no plate: none found" if m is None else "no plate: FALSE PIN"
            res[name, k] += 1
            if m is not None: bad.append((fr["file"], name, "false pin", round(m.score, 2)))
            continue
        if m is None:
            res[name, "missed"] += 1; bad.append((fr["file"], name, "missed")); continue
        dx, dy, dw, dh = tracking.digits_rect(m, REF)
        # digits rect is relative to sub; read it from the same sub-image grown to the right
        got = ocr.read(img[y + dy:y + dy + dh, x + dx:x + dx + dw]).value
        err = max(abs(x + m.x + tracking.PIN_MARGIN - fr["pin"][0]), abs(y + m.y + tracking.PIN_MARGIN - fr["pin"][1]))
        k = "ok" if got == fr["value"] else "misread"
        res[name, k] += 1
        if k != "ok": bad.append((fr["file"], name, got, f"pin err {err}", round(m.score, 2)))
for name in VARIANTS:
    print(f"{name:34}", {k[1]: v for k, v in res.items() if k[0] == name})
for b in bad: print(b)
