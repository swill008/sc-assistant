# Plan: SC Assistant 1.0 (approved 2026-11-01)

Status (2026-11-01): **wave 1 done** (A, B, C, F, H, I, J; see CHANGES.md
v1.0.0). **Wave 2 in progress** (D rename + E version 1.0.0, then
release-notes/1.0.0.md). Wave 3 (release) waits for the user's word.
Approved answers: 1a, 2a, 3a, 4b ("SC Assistant"), 5a.

User's choices recorded during wave 1 (2026-11-01):
- PTU signature data stays a config-file setting only
  (`signature_channel: "ptu"` in config.json); no Settings control.
- Data safety keeps a single `<name>.bak` (the previous save), not a rotating
  set.

## A. Tracking feedback (design agreed earlier: 1a, 2a, 3a)
- Scanner panel chip, always: TRACKING (cyan) / SEARCHING (amber) / FIXED BOX (grey).
- SHOW BOX on: cyan outline around the pin and around the digits, label above
  ("TRACKING ✓  42,000"); amber "SEARCHING…" when the plate is lost; grey
  "FIXED BOX" when tracking is off.
- After DRAW REGION: 3-second confirmation even with SHOW BOX off: "PIN FOUND —
  TRACKING ON", or amber "NO PIN FOUND — FIXED BOX".
- Started: shared colours/words in app/ui/theme.py (TRACK_STATES, TRACK_COLOR,
  TRACK_TEXT), uncommitted.
- Split: A overlay (region_outline.py), B panel chip (mining_panel.py),
  C wiring + confirmation (main.py), D real-screen e2e test.

## B. Tracking after an upgrade (1a)
A box drawn before pins existed has no saved pin. The app learns the pin by
itself the first time the box reads a signature (the plate is on the box at
that moment); the chip shows FIXED BOX until then. A new install has no box,
so its first DRAW REGION saves the pin as now.

## C. Release notes the Gremlin-Platforms way (2a, 3a)
- `release-notes/<version>.md`, starting `## What's new in <version>`, then
  `### New` / `### Changed` / `### Fixed`, user-facing words.
- `tools/release_body.py <version>` builds the GitHub release text: the notes
  file + "How to install" (installer and standalone). The release workflow
  stops when the file is missing or the heading is wrong.
- A self-test fails when app/version.py names a version without a notes file.
- In the app: Settings → Update shows "What's new in vX" from the release body
  before UPDATE (like Gremlin's updater.whats_new; render safely, no HTML).
- CHANGES.md stays as the technical history (measurements, evidence).

## D. Full rename to "SC Assistant" (4b)
- Visible name everywhere: window titles, nav brand "SC ASSISTANT", tray,
  installer, Start menu, README, notes, tests.
- EXE `SCAssistant.exe`; spec/iss renamed; release files
  `SCAssistant-<v>-Setup.exe`, `SCAssistant-windows-x64.zip`; updater asset
  pattern follows.
- Settings folder `%APPDATA%\SC Assistant`: one-time move of
  `%APPDATA%\Citizen Assistant` on first start (ONE-TIME code, marked).
- Single-instance mutex renamed; installer AppMutex lists the new and the old
  name (one-time) so a running Citizen Assistant is never overwritten.
- Installer keeps the same AppId (an upgrade, not a second app); installs to
  `%LOCALAPPDATA%\Programs\SC Assistant`; removes the old Citizen Assistant
  program folder and Start menu entry once (ONE-TIME).
- GitHub repo `swill008/citizen-assistant` → `swill008/sc-assistant` (GitHub
  redirects the old address) — **confirm with the user at that step**.
- User-Agent and updater REPO follow the new name.

## E. Version 1.0.0 (5a)
- app/version.py 1.0.0; first notes file release-notes/1.0.0.md.
- Delete the fork's v1.2.17 / v1.2.18 releases and tags — **confirm with the
  user at that step**; their history moves to CHANGES.md "Earlier (1.2.x)".
- The user's installed 1.2.19 gets 1.0.0 installed once by hand; updates work
  normally after that.

## F. Signature database (agreed: 1a, 2a, 3a)
- scmdb.net game data (versions.json → mining_data-<v>.json), cached, bundled
  file as fallback; live by default, PTU option.
- Separate hand-mining (3,000) and ROC (4,000) mineral lists; salvage stays ours.
- Test comparing the bundled file with the newest scmdb data.
- Measured 2026-11-01: 4.10.2 live and 4.10.3 PTU match our 26 ship ores
  exactly; FPS 3,000 (8 minerals), ROC 4,000 (22 minerals incl. 18 ship ores).

## H. Data safety (code review 2026-11-01, approved 1a) — first in wave 1
One shared safe store for notes.txt, inventory.json, the blueprint registry
and the ore-finder cache: refuse to overwrite a file that could not be read,
keep a .bak of the previous file, retry Windows file locks, read odd encodings
/ changed formats with a fallback instead of crashing, panel shows "NOT
LOADED". Tests force a locked and a broken file. Details:
docs/reviews/2026-11-01-code-review.md (findings 1-6).

## I. Scanner / tracking / update fixes (review, approved 2a) — wave 1
- Pin kept when a monitor only moves (drop it only on a height change).
- TRACKING slider moves in whole steps and saves on release (no save storm).
- UPDATE: wait for the old app without a 60-s limit; relaunch the old version
  if Setup stops (exit 1/2); verify GitHub's sha256 digest; show the version
  actually downloaded; keep the button disabled during the hand-off; wait for
  the update thread at quit.
- Clear errors instead of "No pin icon found" when calibration fails for
  another reason; stale anchor metadata cleared.
- OpenCV/numpy load after the windows appear (not on the GUI thread at start).
- SHOW BOX outline: one placement per move on the same monitor; bounded
  _enforce.

## J. Quality-of-life additions (review, approved 3: b, c, f, g, i)
- b) Rebindable hotkeys in Settings + hotkeys to open panels (check live
  first whether bare F4 is taken from the game's camera).
- c) Honest data age: "updated 2 h ago", amber when past the cache lifetime
  (Hauling, Ore Finder, Combat "LIVE").
- f) DRAW REGION conveniences: right-click cancels, arrow keys nudge 1 px
  (Shift = 10), magnifier on high-DPI screens; picker repaints only what moved.
- g) Re-learn the pin automatically after a resolution change (with B).
- i) First-run guidance when no region is set.

## G. Release — only when the user says so
Merge feature/hud-tracking → main, release 1.0.0 with notes.

## Order
- Wave 1 (parallel agents) — **done 2026-11-01**: H first (data safety), then A, B, C, F, I and J —
  split table before starting; shared files (main.py, settings_panel.py) get
  one owner each.
- Wave 2: D + E (touch files everywhere), then release-notes/1.0.0.md —
  **in progress 2026-11-01**.
- Wave 3: G on the user's word.
Effort: no timing data for this repo; rough guess 2½–3½ hours plus in-game
testing between waves.

## One-time code (rename to SC Assistant)
Marked `ONE-TIME (rename to SC Assistant)` in the code; it can go once no
1.2.x (Citizen Assistant) installs remain. Listed here before each release.
- app/version.py: `OLD_APP_NAME`, `OLD_EXE_NAME`, `OLD_MUTEX_NAME`.
- app/config.py: `_move_old_folder`, `_is_empty_dir` (settings folder move).
- app/main.py: `_old_name_running` and its call in `_acquire_single_instance`.
- installer/sc_assistant.iss: old-name defines; `CitizenAssistant.exe.old`
  clean-up; `OursIsHere` old exe; PrepareToInstall/DeinitializeSetup old exe
  move-aside; `RemoveOldInstall`, `RemoveOldShortcut`, `LinkTarget`,
  `OldDefaultDir`, `SamePath`, `InitializeWizard` folder redirect; the old
  mutex in the real edition's AppMutex.
- installer/test_installer.ps1: step 8 and `BuildOldSetup`.
- tools/make_shortcuts.ps1: `$oldName`, `Test-SourceShortcut`,
  `Remove-OldShortcuts`; uninstall.bat comment.

## Next release (planning, 2026-11-01) — K-N built 2026-11-01, not released
Requested by the user: a button to wipe settings back to defaults; recognise
every scannable item; visible feedback for every read (no silent discards).

- K. [built] Scan limits (decided 2026-11-01; replaces the earlier "ground limit
  30"). Finding: the user's 76,000 Feynmaline (19 ROC deposits x 4,000) was
  lost twice: the reader drops values over max_value 60,000, and the matcher
  allowed at most 8 ground deposits (it would have said DEBRIS x38). Game data
  (scmdb 4.10.2 live clusteringPresets; Star Citizen Wiki): ROC clusters
  10-25 deposits, hand mining 10-21, ship rocks up to 6, salvage scrap up to
  15; whole derelicts not in the data.
  - Limits per kind (1a): ROC 25, hand mining 21, ship 10, salvage 50,
    lower limit 1; a test compares them with the newest scmdb data.
  - Reader accepts up to 100,000 (2a), the largest real reading; above
    that counts as unreadable (red). Default only, no settings-file update.
  - When a number fits two kinds, both are shown on two lines (e.g.
    "ROC x19 · FEYNMALINE / ..." then "or DEBRIS x38").
  - Red border (3a): only while the scan plate is on screen (tracking found
    the pin) and its number cannot be read for about a second in a row; no
    red with tracking off or an empty screen; single dropped frames no.
  - During red (4a): "SCANNED SIGNATURE —"; the matched side and ore name
    keep the last good result.
- L. [built] Per-read feedback (decided with the user, 2026-11-01). The signature
  line becomes two labels:
  - left "SCANNED SIGNATURE <n>": the number from the latest scan, updated
    on every read (today an unreadable crop is dropped silently in
    _on_result and an unconfirmed first read only shows "reading");
  - right "MATCHED SIGNATURE <n>": the signature of the result shown below.
  - Result border (user, 2026-11-01; replaces the earlier "scanned number
    turns green/yellow"): all text, numbers and chips keep today's colours
    (ore names use rarity colours). The card gets a thick result border,
    about 3 px at 100% scale (1a): green = read + exact match, yellow =
    read, no match, red = could not read. When the card greys out 2 s after
    the scan leaves the screen, the border returns to today's thin cyan edge
    (2a). A first read waiting for confirmation shows no colour; only a
    confirmed result colours the border (3a). Border only, no other colour
    changes (4a). "—" when nothing was read.
  - The "NN% MATCH" text moves under the matched signature for now (1b),
    renamed "READ NN%" so it is not confused with the match.
  - Nothing matched: the right side reads "MATCHED SIGNATURE —" (decided 1a).
- M. [built] Recorder for unmatched readings (decided 4b): every reading the app
  cannot match is saved (number, time, small picture of the box, kind of
  scan) and listed in Settings. Review (user, 2026-11-01): when the user
  comes back with missing scans, read %APPDATA%\SC Assistant\unmatched\
  (index.json + pictures) together and decide what to add.
- Data gaps found 2026-11-01: harvestables use 2,000 per plant like salvage
  (grimhex; scmdb clusters 2-10). Decided 1a: 2,000 x 1-10 also shows
  "or HARVESTABLES xn" on the second line under DEBRIS. Agricium 3,885
  (scmdb game files) vs 3,895 (grimhex): decided 2a, keep scmdb's 3,885 and
  let the recorder settle it.
- N. [built] Reset to defaults (decided 5a, 6a): settings only (box, pin, monitor,
  reads/s, TRACKING, SHOW BOX, hotkeys, pinned windows) plus downloaded
  caches; notes, inventory and blueprints are kept. Click twice like QUIT;
  a dated backup folder is kept next to the settings; then the app restarts.

## After 1.0.1 (planning, 2026-11-01) — O, P, Q built for 1.0.2; R built, not released
- O. Download progress (decided 2a, 3a; built, 1.0.2): the UPDATE line reads "Downloading
  v<x> · NN% · <got> of <total> MB", updated every MB (download_setup reads
  1 MB chunks and knows release.size); without a size only "<got> MB". The
  folded UPDATE & RESET heading summary shows "downloading NN%".
- P. Support group removed (decided 1a; built, 1.0.2): it held only the original author's
  coffee/Bitcoin donation request; Settings becomes five groups. The original
  author stays credited in README and LICENSE.
- Q. Window positions persist (decided 1a, 2a, 3a, 4a; built, 1.0.2). Finding: positions
  of the 7 tool panels were saved only in _save_state (normal quit or
  restart), so Task Manager, a crash or Windows shutdown lost every move and
  the open panels; the Settings window was never saved; only combat, UEX and
  notes were pulled back on screen. Decision: save about 1 s after a drag
  ends and when a window opens or closes; all 7 panels plus Settings (the nav
  bar keeps its edge spot); every window pulled fully onto the nearest
  connected screen at start; sizes saved for panels that can be resized.
- R. Whole-window DRAW REGION (decided 1a, 2a, 3a, 2026-11-01; built, not
  released). Analysis: docs/reviews/2026-11-01-plate-capture-analysis.md
  (pin found on 19 of 21 plate frames with a loose box, as today's digits
  box; no false pin on 4 no-plate frames). Decisions: 1a draw around the
  whole signature window (pin, number, orange plate), a digits-only box still
  works; 2a the preview shows the whole window with the pin outlined cyan and
  the digits green; 3a no pin found -> fixed box and "NO PIN FOUND — FIXED
  BOX" as today. Build: find the pin in the box by the bundled reference pin,
  then the orange-mark test, then today's strip left of the box; save the
  user's own pin as today; try up to 5 frames over ~0.5 s; save the window
  as `plate` beside the digits box.

## Parked (2026-11-01): SuperCargo button
A CARGO nav-bar button that shows/hides SuperCargo and its overlay. Planned
method: `--show` / `--hide` / `--toggle` switches added to the user's
SuperCargo fork (features branch builds "SuperCargo-OtherModes"), handled in
its `second-instance` handler (src/main/index.ts ~1005); SC Assistant runs
`SuperCargo-OtherModes.exe --toggle`, auto-detects the install, path setting
as fallback. Merging SuperCargo's overlay into SC Assistant was discussed:
likely small gain (any window over the game forces compositing; SuperCargo
used ~3% CPU), a shown/hidden PresentMon measurement was offered first.
Not decided; resume when the user asks.

## Standing rules for this work
- No releases or installs unless the user says so.
- Tests stay off the main (game) monitor unless needed (then invisible).
- One subject per message; questions in the numbered a)/b) layout.
