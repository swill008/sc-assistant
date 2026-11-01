"""Check the HUD pin tracker on hand-labelled frames of a real flight.

    python -m tools.tracking_selftest

Fixtures: tools/fixtures/hud_track (labels.json + search-area crops) and the
5K2K still tools/fixtures/signal_42000_5k2k.png.
"""
from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import cv2                                   # noqa: E402
import numpy as np                           # noqa: E402

from app.ocr import SignatureOCR             # noqa: E402
from app.tracking import Anchor, digits_rect, find_anchor, locate, search_area  # noqa: E402

FIXTURES = ROOT / "tools" / "fixtures"
TRACK = FIXTURES / "hud_track"
STILL = FIXTURES / "signal_42000_5k2k.png"
STILL_DIGITS = (76, 38, 56, 28)
STILL_PIN = (43, 39)

PIN_TOL = 3                 # px; labels are placed by eye (~2 px, 3 on tinted frames)
MEDIAN_MS = 5.0
# OCR misreads that aren't the tracker's: the pin check still applies
OCR_KNOWN = {
    "f0135.jpg": "the scan tint's blocks turn the 5 into a 6 (61,000 by eye too); "
                 "OCR, not tracking",
}


def _read(path: Path) -> np.ndarray:
    img = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise OSError(f"cannot read {path}")
    return img


def main() -> int:
    failures = 0

    def check(ok: bool, label: str) -> None:
        nonlocal failures
        failures += 0 if ok else 1
        print(f"  {'PASS' if ok else 'FAIL'}  {label}")

    labels = json.loads((TRACK / "labels.json").read_text(encoding="utf-8"))
    box, origin = labels["box"], labels["crop_origin"]
    box_in_crop = (box["left"] - origin[0], box["top"] - origin[1], box["width"], box["height"])
    # 80000 frames are above the app's limit; read them anyway, this checks the rect
    ocr = SignatureOCR(max_value=99999, threads=1)

    cal = next(f for f in labels["frames"] if f.get("calibration"))
    cal_img = _read(TRACK / cal["file"])
    anchor = find_anchor(cal_img, box_in_crop)
    print(f"Anchor from {cal['file']}")
    check(anchor is not None, "find_anchor finds the pin left of the calibrated box")
    if anchor is None:
        print("SOME CHECKS FAILED")
        return 1
    print(f"         template {anchor.template.shape[1]}x{anchor.template.shape[0]}, "
          f"digits {anchor.digits}")
    m0 = locate(cal_img, anchor)
    check(m0 is not None and m0.score > 0.95, "locate finds it again in the calibration frame")
    if m0 is None:
        print("SOME CHECKS FAILED")
        return 1
    # where the template sits relative to the labelled pin top-left
    off = (m0.x - cal["pin"][0], m0.y - cal["pin"][1])

    print("\nLabelled frames")
    imgs = []
    for fr in labels["frames"]:
        img = _read(TRACK / fr["file"])
        imgs.append(img)
        m = locate(img, anchor)
        if fr["pin"] is None:
            check(m is None, f"{fr['file']}  no plate -> no match"
                  + (f" (got {m.x},{m.y} {m.score:.2f})" if m else ""))
            continue
        if m is None:
            check(False, f"{fr['file']}  pin not found (label {fr['pin']})")
            continue
        ex, ey = fr["pin"][0] + off[0], fr["pin"][1] + off[1]
        err = max(abs(m.x - ex), abs(m.y - ey))
        x, y, w, h = digits_rect(m, anchor)
        res = ocr.read(img[max(0, y):y + h, max(0, x):x + w])
        label = (f"{fr['file']}  pin off by {err} px (score {m.score:.2f}), "
                 f"read {res.value} (label {fr['value']})")
        known = OCR_KNOWN.get(fr["file"])
        if known and err <= PIN_TOL and res.value != fr["value"]:
            print(f"  KNOWN {label}: {known}")
            continue
        check(err <= PIN_TOL and res.value == fr["value"], label)

    print("\n5K2K still")
    still = _read(STILL)
    a5 = find_anchor(still, STILL_DIGITS)
    check(a5 is not None, "find_anchor on the still")
    if a5 is not None:
        m = locate(still, a5)
        ok = m is not None
        if ok:
            x, y, w, h = digits_rect(m, a5)
            val = ocr.read(still[y:y + h, x:x + w]).value
            ok = val == 42000
        check(ok, f"locate + OCR on the still reads 42000 (got {val if m else None})")
    # the anchor from the flight finds the still's pin too (same 5K2K scale)
    m = locate(still, anchor)
    if m is not None:
        err = max(abs(m.x - off[0] - STILL_PIN[0]), abs(m.y - off[1] - STILL_PIN[1]))
    check(m is not None and err <= PIN_TOL, "flight anchor finds the pin in the still"
          + (f" (off by {err} px, score {m.score:.2f})" if m else ""))

    print("\nTiming")
    ts = []
    for _ in range(5):
        for img in imgs:
            t = time.perf_counter()
            locate(img, anchor)
            ts.append((time.perf_counter() - t) * 1000)
    med, p95 = float(np.median(ts)), float(np.percentile(ts, 95))
    h, w = imgs[0].shape[:2]
    check(med <= MEDIAN_MS, f"locate on {w}x{h}: median {med:.2f} ms, p95 {p95:.2f} ms "
          f"(limit {MEDIAN_MS:.0f} ms median)")

    print("\nAnchor save/load")
    with tempfile.TemporaryDirectory() as tmp:
        meta = anchor.save(Path(tmp))
        check(meta == {"file": "anchor.png", "digits": list(anchor.digits)}
              and (Path(tmp) / "anchor.png").is_file(), f"save writes anchor.png, meta {meta}")
        back = Anchor.load(Path(tmp), json.loads(json.dumps(meta)))
        check(back is not None and back.digits == anchor.digits
              and np.array_equal(back.template, anchor.template), "load returns the same anchor")
        check(Anchor.load(Path(tmp), {"file": "missing.png", "digits": [1, 2, 3, 4]}) is None
              and Anchor.load(Path(tmp), {}) is None
              and Anchor.load(Path(tmp), {"file": "anchor.png", "digits": "x"}) is None,
              "load returns None for a missing file or bad meta")

    print("\nsearch_area")
    area = search_area(box, 400, 300)
    print(f"         {area}")
    check(area["left"] < box["left"] - 400 - 33 and area["top"] <= box["top"] - 300
          and area["left"] + area["width"] >= box["left"] + box["width"] + 400
          and area["top"] + area["height"] >= box["top"] + box["height"] + 300,
          "covers the box +/- range plus the pin on the left")

    print()
    if failures:
        print(f"{failures} CHECK(S) FAILED")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
