# Whole-plate DRAW REGION: analysis (2026-11-01)

Question (user): can DRAW REGION take the whole signature window (pin, digits and
the plate graphics) instead of a tight box around the digits, with the app finding
the pin and the digits itself, and the preview showing the whole window?

Approved direction before analysis: 1a (whole window; a digits-only box still
works), 2a (preview of the whole window, pin outlined cyan, digits green),
3a (no pin found -> fixed box, "NO PIN FOUND — FIXED BOX").

## Data
`tools/fixtures/hud_track`: 25 frames of a real 5120x2160 flight recording with
hand-checked pin positions and values; 21 show the plate, 4 do not (one with
UNKNOWN marker pins and red WARNING text). Hard frames: blue scan tint (f0135
heavy, f0188, f0224, f0280) and motion blur (f0204, f0280).

The signature window is a small see-through orange rectangle: pin icon, then
the number. Orange compass ticks sit just below it and red warning text can sit
above it.

Boxes drawn around the plate in four ways, relative to the pin: tight, loose,
very loose (takes in the compass ticks), and pin at the box's left edge.
Scripts: `docs/reviews/plate-capture/analyse*.py` (analysis only; no app code
changed).

## Results (21 plate frames, 4 no-plate frames)

| Method | Pin found | Read correctly | False pin on no-plate frames |
|---|---|---|---|
| Today: digits box, `find_anchor` looks left of it | 19 | 18 | — |
| A. Orange blob inside the box (pin-shaped, left-most) | 17-19 by box | 15-16 | 0 of 4 |
| B. Match the bundled reference pin inside the box (`tracking.locate`) | 17, the same for every box size | 16 | 0 of 4 |
| A + B together, loose or very loose box | **19** | — | 0 of 4 |
| A + B together, tight box | 17 | — | 0 of 4 |

- Missed by every method, today's included: f0135 (heavy tint) and f0280
  (tint and blur). These are mid-flight frames; DRAW REGION is pressed once on a
  steady view.
- f0232 (clean) is missed with a tight box by both A and B, found with a loose
  one: a light cloud behind the pin lowers its contrast.
- Misreads are the reader's, not the locating: f0261 reads 77,020 / 7,020 for
  17,020 with every method including today's.
- The digits position from the pin (the existing "pin heights" geometry) read
  the right number on every frame where the pin was found and the reader was
  not at fault.
- B is independent of how big the box is drawn and found no pin in the four
  no-plate frames, including the one with UNKNOWN marker pins.

## Conclusion
Whole-window capture works as well as today's digits box on these frames, and
better than today's when the box is drawn loosely around the plate (the easy way
to draw it). Recommended build:

1. In the drawn box, find the pin by matching the bundled reference pin (B),
   then by the orange-blob test (A), then today's strip left of the box (so a
   digits-only box still works).
2. Save the user's own pin from the screen as today; tracking while flying is
   unchanged.
3. Grab a few frames over about half a second at DRAW REGION and use the first
   that gives a pin, so one blurred or tinted frame doesn't fail calibration.
4. Save the drawn window as `plate` next to the digits box for the preview
   (whole window, pin cyan, digits green); old settings without `plate` show
   the digits as today.

Not verified: resolutions other than 5120x2160 (the reference pin is scaled
by screen height; no fixtures at other sizes), and other ships' HUD colours.
