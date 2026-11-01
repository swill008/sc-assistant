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
from app.tracking import (  # noqa: E402
    PIN_MARGIN, PIN_REFERENCE, Anchor, digits_rect, find_anchor, find_anchor_in_box, locate,
    reference_anchor, search_area,
)

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
# Windows drawn round the whole signature plate, relative to the labelled pin
# top-left (24x28 at 5K2K), and the fewest frames (of 21) each must find the
# pin on: docs/reviews/2026-11-01-plate-capture-analysis.md
PLATE_BOXES = {
    "tight": ((-12, -8, 150, 44), 17),
    "loose": ((-35, -25, 195, 80), 19),
    "very loose": ((-70, -40, 260, 150), 19),
    "pin at left edge": ((-4, -6, 150, 40), 17),
}
DIGITS_ONLY = ((33, 1, 57, 25), 19)     # today's box round the digits
BOX_PIN_TOL = 6         # px; the orange-mark fallback cuts the bright part only
# misreads in a plate box that are the reader's, not the locating's
OCR_KNOWN_BOX = {
    "f0261.jpg": "reads 77,020 for 17,020 with every method, today's included",
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

    print("\nfind_anchor_in_box (whole signature window)")
    check(PIN_REFERENCE.is_file() and reference_anchor(2160) is not None,
          f"bundled reference pin loads ({PIN_REFERENCE.name})")
    frames = list(zip(labels["frames"], imgs))
    table = []
    for name, ((ox, oy, w, h), need) in [*PLATE_BOXES.items(), ("digits only", DIGITS_ONLY)]:
        found = read_ok = known = false_pin = 0
        notes = []
        for fr, img in frames:
            # no plate: the window drawn where the plate sits when calibrated
            px, py = fr["pin"] or cal["pin"]
            bx, by = px + ox, py + oy
            r = find_anchor_in_box(img, (bx, by, w, h), 2160)
            if fr["pin"] is None:
                false_pin += r is not None
                continue
            if r is None:
                notes.append(f"{fr['file']} missed")
                continue
            a, (pdx, pdy, pw, ph) = r
            tx, ty = bx - pdx, by - pdy
            # digits only: find_anchor cuts the bright part only, which can sit a
            # few px off the labelled icon corner; the read checks it instead
            err = 0 if name == "digits only" else max(abs(tx + PIN_MARGIN - px),
                                                      abs(ty + PIN_MARGIN - py))
            if err > BOX_PIN_TOL or (pw, ph) != (w, h):
                notes.append(f"{fr['file']} pin off by {err} px, plate {pw}x{ph}")
                continue
            found += 1
            dx, dy, dw, dh = a.digits
            val = ocr.read(img[max(0, ty + dy):ty + dy + dh, max(0, tx + dx):tx + dx + dw]).value
            if val == fr["value"]:
                read_ok += 1
            elif fr["file"] in OCR_KNOWN_BOX or fr["file"] in OCR_KNOWN:
                known += 1
                notes.append(f"{fr['file']} KNOWN read {val}")
            else:
                notes.append(f"{fr['file']} read {val} (label {fr['value']})")
        table.append((name, found, read_ok, false_pin))
        check(found >= need, f"{name}: pin found on {found} of 21 (need {need})")
        check(read_ok + known == found, f"{name}: digits read the label on {read_ok} of {found}"
              + (f" + {known} known OCR misread(s)" if known else ""))
        check(false_pin == 0, f"{name}: no pin on the 4 no-plate frames (got {false_pin})")
        for n in notes:
            print(f"         {n}")
    print("\n         box               found  read  false pin")
    for name, found, read_ok, false_pin in table:
        print(f"         {name:17} {found:5}  {read_ok:4}  {false_pin:9}")

    s = 1440 / 2160
    (ox, oy, w, h), need = PLATE_BOXES["loose"]
    found = false_pin = 0
    for fr, img in frames:
        small = cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
        px, py = fr["pin"] or cal["pin"]
        bx, by = round((px + ox) * s), round((py + oy) * s)
        r = find_anchor_in_box(small, (bx, by, round(w * s), round(h * s)), 1440)
        if fr["pin"] is None:
            false_pin += r is not None
        elif r is not None:
            tx, ty = bx - r[1][0], by - r[1][1]
            found += max(abs(tx + PIN_MARGIN - px * s), abs(ty + PIN_MARGIN - py * s)) <= BOX_PIN_TOL
    check(found >= need and false_pin == 0,
          f"1440-high resize, loose window, screen_height 1440: pin found on {found} of 21 "
          f"(need {need}), {false_pin} on the no-plate frames")

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
