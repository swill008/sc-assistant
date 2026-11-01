# Changes

## v1.2.19 — 2026-11-01

The scanner follows the signature plate as the HUD sways in flight.

### New: HUD tracking

**What happened.** In flight Star Citizen's HUD moves with the ship's
"physics". A 30-second recording of the user's 5120×2160 screen at 10 frames a
second showed the signature plate moving 218 px left to 250 px right and 43 px
up to 227 px down around the calibrated box, often 100+ px within 0.1 s. The
fixed box read a signature in 19 of 300 frames.

**Change.** SELECT now also saves the plate's orange pin icon from just left of
the digits (`anchor.png` in `%APPDATA%\Citizen Assistant`, `anchor` in
`config.json`). Each read captures the box plus a search range around it, finds
the pin and OCRs the digits at their fixed offset right of it
(`app/tracking.py`). The pin is the anchor because it is the same in every
ship; the rest of the HUD (compass, dashes) differs per ship. With no plate on
screen the OCR is not run.

- **TRACKING** in Settings → *Scanning*: `OFF` or ±50…±800 px (default ±400
  across, ±300 up and down for a 2160-px-high screen, scaled for other heights;
  saved as `tracking_range`). `OFF`, or no saved pin, is the fixed box as before.
- SHOW BOX follows the digits being read.
- No pin next to the box at SELECT: amber note, tracking off.
- A box rescaled for a new resolution or monitor turns tracking off until the
  next SELECT (the saved pin is for the old size).

**Result** on the recording (same ±400×±300 range, app OCR, 60,000 limit):

| | Fixed box | Prototype | Tracking |
| --- | --- | --- | --- |
| Frames with the pin found | — | 203 | 281 |
| Frames read | 19 | 188 | 259 |
| Search time per read | — | 41 ms | 1.25 ms (95%: 3.8 ms) |
| Matches on frames with no plate | — | 0 | 0 |

The plate was visible in all but the first ~11 frames. The search is
coarse-to-fine: a quarter-size orange (R − B) map picks five candidates, each
checked at full resolution in colour; matches from 0.6 up count (every match
from 0.55 up on the recording was a real, tinted or blurred plate; frames
without one scored 0.34 or less).

### Tests

- `tools/tracking_selftest.py` with `tools/fixtures/hud_track/`: 25 frames of
  the recording, labelled by eye (value and pin position; 4 without a plate,
  including UNKNOWN markers and WARNING text by the box; blue-tinted and
  motion-blurred plates; the largest offsets in each direction). The anchor is
  built from the frame where the plate sits on the box; the pin is found within
  0–1 px in all 21 plate frames, no match in the 4 without; OCR reads the
  labelled value in 20 (f0135: the tint makes 51,000 read as 61,000, listed as
  known); median search time ≤ 5 ms is checked.
- `tools/scan_selftest.py`: the TRACKING control, the scan step (search area,
  OCR only on a match, none without one, the fixed box at `OFF`), calibration
  saving the pin or showing the note, and tracking turned off on a rescale.
- `tools/scan_e2e_selftest.py`: on the real screen, calibrate on the 5K
  signature, move it 150 px right and 100 px down, and the running app still
  reads 42,000 while the fixed box alone reads nothing there; SHOW BOX follows;
  with the plate gone no value and no OCR call; TRACKING `OFF` goes back to the
  fixed box. 42/42 on a 125% monitor. On the game monitor the "plate gone" step
  fails while the game shows a real plate in the search area (correctly tracked);
  run `--primary` with the game closed.

### Known limits

- The OCR sometimes drops a zero on a blurred 80,000 plate and reads 8,000,
  which is a valid signature (debris ×4). 80,000 itself is above the 60,000
  limit and correctly ignored. Not changed in this release.
- Very heavy scan tint can turn a 5 into a 6 (one labelled frame).

## v1.2.18 — 2026-11-01

Adds a Windows installer next to the standalone download. The program itself
is unchanged from v1.2.17 (see below for its fixes).

### New: installer

Each release now has two downloads with the same program inside:

- **CitizenAssistant-X.Y.Z-Setup.exe** — installs for the current Windows user
  only (no administrator rights) into `%LOCALAPPDATA%\Programs\Citizen
  Assistant`, with a Start menu entry, an uninstaller (also in *Settings →
  Apps*), and optional desktop and *Start when Windows starts* shortcuts.
- **CitizenAssistant-windows-x64.zip** — the standalone folder, as before.

Running a newer Setup updates in place. It moves the old program files aside
first and removes them only once the new ones are in; if the install fails, or
Citizen Assistant is still running, it puts the old version back and says so.
Settings in `%APPDATA%\Citizen Assistant` are never touched by install, update
or uninstall. The script, `installer/citizen_assistant.iss` (Inno Setup 6),
follows the Gremlin-Platforms installer.

### Release and build workflows

- Releases publish both downloads; a tag push releases automatically (Actions
  is now enabled on this fork), and a release can also be run by hand for an
  existing tag.
- Every push to `main` runs the headless self-tests and builds both downloads
  as a test artifact.
- The release text comes from this file.

### Tests

`installer/test_installer.ps1` installs the built Setup silently into a
throwaway folder and checks: a fresh install (files, Start menu shortcuts and
target, *installed apps* entry and version, per-user); that the installed
program starts and stays running with no error log; an upgrade in place; an
upgrade while the program's files are in use (refused, previous version put
back intact); the uninstall (files, shortcuts and entry removed); and that
`%APPDATA%\Citizen Assistant` is byte-for-byte unchanged. All 26 checks passed
on the v1.2.17 build.

Note: building from a deep folder fails on Windows' 260-character path limit
(the deepest bundled file is 111 characters); keep the checkout in a short
path.

## v1.2.17 — 2026-11-01

Fixes for 5K2K and mixed-scaling desks, and for game stutter while the scanner
runs; new scanner settings; a QUIT button; updates now come from this fork.
Measured on Windows 11, Ryzen 7 9800X3D (8 cores, SMT off), RTX 4090, main
monitor 5120×2160 at 150% beside two 1920×1080 at 125% and a 3840×2160 TV at
300%.

### Fixed: the scanner read nothing on a 5K2K screen

**What happened.** Calibrating on the 5120×2160 monitor stored a 28×14 box
around a signature whose digits are about 56×28, and OCR returned no text.

**Cause.** The region picker was one window stretched over every monitor. Qt
gives a window one scale factor, taken from the monitor it lands on, here the
TV at 300% (a 25725×9072 native window). Mouse positions were therefore in
300% units, but the box was converted to pixels with the main screen's 150%,
so every box was stored at half its width and height. Only mixed-scale desks
were affected.

**Evidence.** On four 5120×2160 screenshots of a 42,000 signature, the stored
28×14 box read nothing in all four; the same box at 56×28 read `42,000` in all
four (confidence 0.82–0.85). The OCR itself handles 5K2K text fine.

**Change.** `app/ui/region_selector.py` opens one picker window per monitor,
each with that monitor's scale, and takes the box from the physical cursor
position (`win32.cursor_pos`, `GetPhysicalCursorPos`), so the stored box is
exactly the one dragged. The size label shows physical pixels. The picker also
no longer needs about 1 GB of image memory for a desk-sized window.

**Action needed.** If you calibrated with an older build, press SELECT again.

### Fixed: frame hitches while the scanner runs

**What happened.** With the overlay running, Star Citizen had about 10× more
frame hitches than with it closed (PresentMon, 150 s per phase, both orders:
33–53 hitches versus 3–6; worst 1% of frames 34–41 ms versus 18–19 ms).

**Cause.** `rapidocr-onnxruntime` builds its ONNX Runtime sessions with the
library defaults: a thread pool as wide as the CPU whose workers spin while
waiting. Every read (8 a second) burst across more than 6 of the 8 cores and
took them from the game. Limiting the overlay to two cores at low priority from
outside brought the game back to the overlay-closed numbers, which confirmed
the cause.

**Change.** `app/ocr.py` builds the sessions with `ocr_threads` threads
(default 1), no spinning and sequential execution; the scanner thread runs at
low priority (`app/main.py`).

**Result** (the 42,000 crop, game running):

| OCR setup | CPU per read | Cores busy during a read | Time per read |
| --- | --- | --- | --- |
| Before | 37.7 ms | 6.3 | 6 ms |
| After (`ocr_threads: 1`) | 6.4 ms | 0.4 | 17 ms |

### New: scanner settings for resolution, scaling and read rate

- **MONITOR** (*Signature capture region*): every monitor with its real
  resolution and Windows scaling, read from Windows. SELECT opens on the chosen
  monitor.
- **The box follows monitor changes.** The monitor's rect is recorded with the
  box (`region_monitor`). If its resolution or position changes, or you choose
  another monitor, the box is moved to match (`app/display.py`, `rescale`:
  offset from the screen centre scaled by the height ratio, as the HUD scales)
  and an amber note says so.
- **READS / S** (*Scanning*): 1–8 reads a second, applied immediately, saved as
  `poll_ms`. Default is now 4 (`poll_ms` 250); installs on the old 125 default
  move to 250 once (`scan_tuning_version` 2).
- **SHOW BOX** (*Scanning*): draws the capture box on screen. The outline sits
  just outside the box, is click-through and is always hidden from capture
  (`WDA_EXCLUDEFROMCAPTURE`); it is placed in physical pixels so it is exact on
  any monitor scale. Off by default (`show_region_outline`).

### New: QUIT on the nav bar

`✕` only hides the overlay; QUIT ends it. One click arms it (red, `QUIT?`), a
second within 2.5 s quits; otherwise it disarms.

### Changed: updates come from this fork

`app/updater.py` pointed at `fishtaco7/citizen-assistant`, so UPDATE in this
fork would have replaced its fixes with the upstream code. CHECK and UPDATE now
use `swill008/citizen-assistant`; the HTTP User-Agent names the fork. Nothing
updates by itself.

### Tests

- `tools/scan_selftest.py`: OCR thread cap; one picker window per monitor at
  that monitor's scale; exact drag on all four monitors; picker on the chosen
  monitor only; rescale maths; `poll_ms` migration; READS / S slider; monitor
  list labels; outline position on every monitor, click-through and capture
  exclusion; QUIT arming; update source. Written first and failing on v1.2.16.
- `tools/scan_e2e_selftest.py`: on the real screen, a 5K2K screenshot crop at
  1:1 → picker → capture → OCR reads 42,000; SHOW BOX leaves the capture
  byte-for-byte unchanged; then the real `OverlayApp` with a temporary config:
  the running scanner reads 42,000 at low priority, READS / S changes the live
  interval and the saved file, SHOW BOX shows and F4 hides the outline, a
  resolution change and a monitor change move the box, QUIT stops the scanner.
  Passed on the 125% monitor and (`--primary`) the 150% 5K2K monitor.
- The existing `selftest`, `workflow_selftest`, `refinery_selftest`,
  `combat_selftest` and `blueprint_selftest` still pass.

### Known limits

- A box moved for a new resolution or aspect ratio is a best estimate of where
  the HUD went; check SHOW BOX or SHOW PREVIEW and press SELECT if it is off.
- Any overlay window over the game, SHOW BOX included, makes Windows composite
  the game's frames (measured: 60.6 → 69.7 FPS with every overlay window
  hidden). Not changed in this release.
