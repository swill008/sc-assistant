# Changes

## v1.0.4 — 2026-11-01

A VOICE group with four speech engines, a DEBUG group with scan history,
bad-read pictures and logging, the preview's green box on the digits the
reader finds, and a built-in reader range up to 120,000.

### VOICE group

**What happened.** Announcements used one fixed voice (QtTextToSpeech's
default) with only ON/OFF and volume, under LOOK & SOUND. The user asked for
every free method side by side, clearly labelled, to compare and pick
(research: `docs/reviews/2026-11-01-voice-research.md`, scripts in
`docs/reviews/voice/`).

**Change.** A new Settings group **VOICE** (id `voice`, after LOOK & SOUND;
the Voice part moved out of LOOK & SOUND). Rows: VOICE ON/OFF and VOLUME
(moved), ENGINE, VOICE (the engine's voices; Piper and Kokoro with licence
and size or `downloaded`), a DOWNLOAD row only while the chosen voice needs
files (`Needs a <N> MB download` + DOWNLOAD, then `NN% · <got> of <total> MB`
+ CANCEL; TEST disabled until done), SPEED 0.5-2.0 in 0.1 steps, SAYS (three
styles), TEST (19 Feynmaline deposits, 57,000, in the chosen style:
`Feynmaline, times 19` / `Nineteen Feynmaline` / `Feynmaline, nineteen
deposits, fifty-seven thousand`) and a grey note line (licence / online
notes, errors). Summary: `<engine> · <voice> · <speed>×` with short engine
names (`Windows`, `Piper`, `Kokoro`, `Microsoft online`), `off · ` in front
while off, ` · downloading NN%` after while downloading; LOOK & SOUND's
summary is now `UI NN%`. New `config.json` keys: `voice_engine`
(`"windows"`), `voice_voice` (`""`), `voice_speed` (`1.0`), `voice_style`
(`"count_after"`).

Engines (`app/tts/`):

| id | Menu label | Notes |
| --- | --- | --- |
| `windows` | Windows voices (built in, offline) | QtTextToSpeech, engines `winrt` and `sapi` (the `mock` test engine hidden); voices from both, labelled with the engine |
| `piper` | Piper (offline, natural · add-on, GPL-3.0) | `piper-tts` 1.8.0 (`cp39-abi3-win_amd64` wheel) + `pathvalidate` from PyPI (about 33 MB; Hebrew model, training code, templates and images not extracted, about 22 MB saved) + a voice (60-130 MB) from `huggingface.co/rhasspy/piper-voices` at a pinned revision; 17 English voices, only public-domain / CC0 / CC-BY dataset licences; the ONNX session is built by the app so the thread limit holds |
| `kokoro` | Kokoro (offline, most natural · add-on, GPL-3.0, uses more CPU) | `kokoro-onnx` 0.6.1 + `phonemizer` 3.4.0 + `espeakng-loader` 0.2.4 and their small dependencies (`joblib`, `cloudpickle`, `attrs`, `dlinfo`, `typing-extensions`) from PyPI (about 10 MB), the int8 model (about 88 MB) and per-voice files (about 0.5 MB) from `onnx-community/Kokoro-82M-v1.0-ONNX` at a pinned revision; 28 English voices, Apache-2.0 |
| `edge` | Microsoft online voices (online: sends the phrase to Microsoft) | `edge-tts` 7.3.1, LGPL-3.0, bundled in the EXE as plain `.py` files (`sc-assistant.spec`); every phrase goes to Microsoft's speech service (`speech.platform.bing.com`); the voice list is cached in `%LOCALAPPDATA%\SC Assistant\voices\edge\voices.json`, a built-in list of 8 until the first fetch |

- `app/tts/base.py` `Engine` (`available`, `voices`, `needs_download`,
  `download(voice_id, progress, cancelled)`, `synth(text, voice_id, speed)`);
  the Windows engine speaks directly.
- `app/tts/worker.py` `TtsWorker`: one queue on one below-normal-priority
  thread, ONNX limited to 1 thread, stale phrases dropped, models loaded once
  per engine and voice.
- `app/tts/player.py`: PCM through `QAudioSink`, MP3 through `QMediaPlayer`,
  both from a `QBuffer` (no temporary files).
- `app/tts/phrases.py` `STYLES = ("count_after", "count_before",
  "with_signature")`: `Borase, times 3` (as before) / `Three Borase` /
  `Borase, three rocks, fourteen thousand four hundred`; numbers as words in
  the second and third.
- `app/voice.Voice` keeps `say`, `set_enabled`, `set_volume`, `available`,
  `stop` and adds `set_engine`, `set_voice`, `set_speed`, `set_style`,
  `test`. Any engine failure (not installed, not downloaded, synthesis or
  playback error) speaks the phrase with a Windows voice, logs a warning and
  shows it on the note line.
- Tests: `tools/tts_selftest.py` (phrases, facade, worker, Windows voices,
  player; always at volume 0), `tools/neural_selftest.py` (add-on download,
  pins, tampered files, cancel, licence filter; offline stand-in, `--live`
  checks the pins), `tools/edge_selftest.py` (fake transport; `--live` asks
  Microsoft).

**Add-ons (licence decision, 2026-11-01).** SC Assistant is MIT; Piper and
Kokoro's phonemizer / espeak-ng are GPL-3.0, and bundling them would most
likely make the EXE a GPL-3.0 combined work. They are therefore optional
add-ons, never bundled: `app/tts/addons.py` downloads them on demand into
`%LOCALAPPDATA%\SC Assistant\voices\<engine>\lib` (engine) and
`...\<engine>\voices` (voices). Every wheel, model and voice file is pinned
by exact name and SHA-256 (wheels also checked against PyPI's JSON) and a
file that does not match is deleted and refused; the lib folder is appended
to `sys.path` only when that engine is used, so the app's own numpy and
onnxruntime always win. Sizes are shown before download.

Measured (research, 8 cores, below-normal priority, 1-2 ONNX threads, test
phrase about 2.1 s of audio): Windows plays directly (about 12 % CPU); Piper
0.09-0.24 s to synthesise, first load 4.8 s, +118 MB RAM; Kokoro 0.74-1.1 s,
19 % CPU for about 1 s, +166 MB; Microsoft online about 0.6 s including the
network, about 2 % CPU. None conflicts with the app's onnxruntime 1.31 /
numpy 2.5.

### Reader range built in; largest scans

**What happened.** The user scanned 112,000 (Aphorite, flying above Cellin),
above the reader's 100,000 limit, so it was counted as unreadable. The range
was saved in `config.json` (`min_value`, `max_value`), so a raised default
would not have reached existing installs without a reset (the old 60,000
limit had stayed alive the same way).

**Change.** The range is built in: `app/ocr.py` `READ_MIN = 2000`,
`READ_MAX = 120000` (a margin above 112,000), no longer read from or saved in
`config.json`; a `min_value` / `max_value` left in an existing
`config.json` is dropped on load. 112,000 is now read, shown as `SCANNED SIGNATURE 112,000`
with a yellow border (it fits no single kind) and saved by the recorder.
README gets a *Largest scans* table (game files: ROC 10-25, hand mining
10-21, ship rocks up to 6, salvage scrap up to 15; real readings 76,000
Feynmaline = ROC ×19, 57,000 Aphorite = hand mining ×19, 112,000 Aphorite
above Cellin = no single kind: not a multiple of 3,000, 28 ROC or a mix such
as 8 Aphorite + 22 ROC would fit, likely the ship scanner adding nearby
deposits, unverified), updated from the recorder's unmatched readings.

### DEBUG group: scan history and bad reads (911423e)

**Change.** Settings gets a group **DEBUG** (id `debug`, last), part *Scan
debugging*, both switches off by default:

- **SCAN HISTORY** (`debug_scan_history`) keeps the last 50 reads in
  `scan_history.txt` in the settings folder, newest last:
  `<time> | read <n> | conf <c> | top <match> exact|~ | 2nd <match> |
  confirmed yes|no | shown yes|no | border <b> | track <state>`. Written at
  most once a second from a GUI-thread timer, never on the scanner thread.
  **OPEN HISTORY** opens it.
- **SAVE BAD READS** (`debug_save_bad_reads`) saves the digits picture as
  PNG to `bad_reads/` when tracking is locked on the plate but the read
  fails: at most one a second, newest 200 kept, name
  `<time>-<seq>-<state>-x<l>-y<t>-<w>x<h>.png`. **OPEN FOLDER** opens it.
- Summary while closed: `history on|off · saver on|off`.
- RESET SETTINGS turns both off and removes `scan_history.txt` and
  `bad_reads/` (`RESET_REMOVE`).
- Test: `tools/debug_selftest.py`.

### Logging (8eaee7e)

**What happened.** The EXE has no console, and several errors in `main` and
`config` were swallowed with `except OSError: pass`, so problems left no
trace.

**Change.**

- `app/applog.py`: `app.log` next to the settings, one rotating handler on
  the root logger (1 MB, 3 backups `app.log.1`-`.3`). WARNING and above
  normally; unhandled errors from any thread are written too (they still go
  to `error.log`).
- **DETAILED LOG** (`debug_detailed_log`, Settings → DEBUG → *Logs*) raises
  only the app's own loggers (`app.*`) to DEBUG, switchable while running;
  other libraries stay at WARNING. New trace lines in `main`, `updater`,
  `sigsource` and `tracking`; the swallowed errors in `main` and `config`
  are now logged. Summary adds ` · log detailed`.
- **OPEN LOG** opens `app.log`; **VIEW LOG** opens `app/ui/log_viewer.py`, a
  640 × 420 always-on-top LOG window that tails the file (last 2,000 lines,
  polled every second): ALL / WARNING+ / ERROR and text filters, COPY,
  OPEN FILE, `LIVE` / `PAUSED` when scrolled up; position saved as
  `logviewer_pos`.
- **EXPORT DIAGNOSTICS** writes `SC Assistant diagnostics <date time>.zip` to
  the Desktop (else the settings folder) and opens its folder: `system.txt`
  (version, build, OS, Python, Qt, detailed on/off, monitors, game monitor,
  region), `config.json`, `error.log`, `app.log*`, `scan_history.txt`, the
  newest 20 `bad_reads` pictures and `unmatched/index.json` with the newest
  20 pictures. Never `notes.txt`, `inventory.json`,
  `unlocked_blueprints.json`, `refinery_jobs.json`, `active_run.json` or
  `workflow_wallet.json` (`DIAG_EXCLUDE`).
- RESET SETTINGS turns DETAILED LOG off and keeps the logs (`app.log*` in
  `RESET_KEEP`).
- Tests: `tools/applog_selftest.py`, `tools/logviewer_selftest.py`, plus
  `debug_selftest`, `settings_extra_selftest` and `settings_persist_selftest`.

### Preview: green box on the digits found (d1e7018)

**What happened.** With a whole-window plate, SHOW PREVIEW drew the green box
on the digits area placed from the pin, which is wider than the number, so
the box looked off the number (about 16 px off its centre on the 5K2K
fixture).

**Change.** `plate_view` now draws the green box around
`SignatureOCR.digit_box` of that area, the same trim the reader uses, so it
is centred on the number; no green box when no digits stand out. Reading is
unchanged. `settings_extra_selftest` checks the rendered preview at UI 1.0
and 1.5; `scan_selftest` and `scan_e2e_selftest` fail on the old code.
`tools/_testguard.py` now puts a test's `--root DIR` on `sys.path` before
importing `app`, so old-code runs really test DIR.

## v1.0.3 — 2026-11-01

DRAW REGION takes the whole signature window.

### Whole-window DRAW REGION (plan item R)

**What happened.** DRAW REGION needed a box drawn tightly around the digits
only, about 60 × 26 physical pixels on a 5120 × 2160 screen: hard to draw, and
the preview showed only those digits, so it was hard to see whether the box
sat on the plate.

**Change.** Draw around the whole signature window (pin, number and the
orange plate); a loose box is fine and a digits-only box still works (1a).
`tracking.find_anchor_in_box(image, box, screen_height)` finds the pin inside
the drawn box in this order: the bundled reference pin
(`app/data/pin_reference.png`), scaled by screen height / 2160, matched with
`tracking.locate`; then the left-most pin-shaped orange mark (about 28 px high
at 2160); then today's strip left of the box, treating it as a digits box. It
returns the user's own pin (saved as `anchor.png` as before) and the drawn
window relative to it. DRAW REGION grabs up to 5 frames over about 0.5 s and
uses the first that gives a pin. With a pin, `region` is the digits box placed
from the pin (same meaning as before, so scanning and tracking are
unchanged) and the window is saved as `plate` (`{"dx", "dy", "w", "h"}`,
relative to the pin) in `config.json`. Without a pin: the fixed box and
`NO PIN FOUND — FIXED BOX` as before (3a). A height change or a missing
pin file drops `plate` with the pin; a pin learned from a scan saves none. **SHOW PREVIEW** shows the whole window with the pin outlined in
cyan and the digits in green while tracking (2a); without a saved window, the
digits as before.

**Analysis** (`docs/reviews/2026-11-01-plate-capture-analysis.md`; 25 frames
of a real 5120 × 2160 recording, 21 with the plate, 4 without). Pin found:
today's digits box 19 of 21; the bundled pin match alone 17 for every box
size; the orange-mark test alone 17-19 by box; both together 19 with a loose
or very loose box and 17 with a tight one. No false pin on the 4 frames
without a plate (one has UNKNOWN marker pins and red warning text). The two
frames missed by every method, today's included, are heavily tinted or
blurred mid-flight frames. Where the pin was found the digits placed from it
read the right number except where the reader itself misreads (17,020 read
as 77,020 / 7,020 with every method). Not verified: other resolutions (no
fixtures; the reference pin is scaled by height) and other ships' HUD
colours.

## v1.0.2 — 2026-11-01

Download progress for UPDATE, the Support group removed from Settings, and
window positions that survive a crash.

### Download progress (plan item O)

**What happened.** UPDATE showed one fixed line for the whole download of the
Setup (about 100 MB), so a slow download looked like a hang.

**Change.** `updater.download_setup(timeout=300.0, cancelled=None,
progress=None)` calls `progress(got_bytes, total_bytes)` once at the start
with `(0, total)` and after every 1 MB chunk; `total` is the release asset's
size, 0 when GitHub gives none. `_UpdateWorker` re-emits it as
`progress = Signal(int, int)`, queued to the GUI thread. The UPDATE line reads
`Downloading v<x> · NN% · <got> of <total> MB` (MB = bytes / 1,048,576, whole
numbers, NN never above 100), or `Downloading v<x> · <got> MB` without a size.
The folded UPDATE & RESET heading shows `downloading NN%` (or
`downloading <got> MB`) while downloading, then its usual summary.

### Support group removed (plan item P)

**Change.** The SUPPORT group held only the original author's coffee/Bitcoin
donation request. It is removed with `BTC_ADDRESS`, the donation text, the
COPY button and `_copy_btc`; `SECTION_IDS` is now `("scanner", "scan_data",
"hotkeys", "look", "update")`, five groups. A saved `"support"` id in
`settings_open` is dropped at start. The original author stays credited in
README and LICENSE.

### Window positions persist (plan item Q)

**What happened.** The seven tool panels' positions and the open panels were
saved only by `_save_state`, on a normal quit or restart, so ending the app in
Task Manager, a crash or a Windows shutdown lost every move. The Settings
window's position was never saved, and only COMBAT, UEX and NOTES were pulled
back on screen at start.

**Change.** `app/main.py` installs an event filter on the seven tool panels
(mining, ore finder, hauling, inventory, combat, UEX, notes) and the Settings
window (`_WindowWatcher`): every Move, Show and Hide event restarts one 1 s
single-shot timer that calls `_save_state`. The filter is installed after the
windows are placed at start, and nothing is scheduled while `_resetting` or
after QUIT/dispose (`_stop_saving`). New config key `settings_pos` (default
`None`): until Settings has a position (restored, or placed by
`place_default(self.panel)` the first time it opens) it is not written. At
start every saved position is restored and `fit_on_screen()` (new, in
`app/main.py`) moves each of the eight windows fully inside the available area
of the screen holding its centre, or the nearest screen when none does; a
window larger than that area is aligned by its top-left, and a window already
fully on screen is not moved. Settings is fitted again each time it opens and,
once placed, reopens where it was left instead of under the scanner panel. The nav bar is left out;
it keeps its edge placement. All eight windows have fixed sizes, so no sizes
are saved. Panel files are not changed.

## v1.0.1 — 2026-11-01

The first published release of **SC Assistant** (Citizen Assistant renamed;
the version number starts again at 1.0). 1.0.0 was a local test build and was
never published, so everything below is new in 1.0.1. Also: data safety for the user's own files, visible HUD-tracking
feedback, signature data from scmdb.net, release notes, update and scanner
fixes, rebindable hotkeys, window pins and first-run guidance, scan limits from
the game data, feedback on every read, a recorder for unmatched readings, a
settings reset and collapsible Settings sections.

### Scan limits from the game data

**What happened.** The user's 76,000 Feynmaline (19 ROC deposits × 4,000) was
lost twice: the reader dropped every value over `max_value` 60,000, and the
matcher allowed at most 8 ground deposits (it would have said DEBRIS ×38).

**Change.** Limits per kind, from scmdb 4.10.2 live `clusteringPresets` and the
Star Citizen Wiki (ROC clusters 10-25 deposits, hand mining 10-21, ship rocks
up to 6, salvage scrap up to 15; whole derelicts are not in the data):

- Module constants in `app/mining.py`, lower limit 1: ship 10 (`MAX_CLUSTER`,
  unchanged), ROC 25, hand mining (FPS) 21, salvage debris 50,
  harvestables 10. The bundled `signatures.json` ground `max_cluster` (8)
  became `roc_max_cluster` 25 and `fps_max_cluster` 21, so it does not lower
  them; `MiningData.ground_max_cluster` is now the larger of the two.
- Debris no longer appends `OR ROC DEPOSIT ×n` to its detail line; the other
  kind is the panel's second line instead.
- New kind `harvest`: base 2,000 (like debris, per grimhex), 1-10 plants,
  label `HARVESTABLES`, detail `PLANTS` (`harvest` in `signatures.json`;
  scmdb Harvestables clusters 2-10). A multiple of 2,000 gives debris first and harvest
  second when both fit.
- `MiningData.lookup(value)` returns every candidate: exact matches first,
  then fuzzy ones, closest first. Before, fuzzy matches were dropped whenever
  an exact one existed. Order of exact matches (user decision): ship ore first;
  up to 30,000 (`SALVAGE_FIRST_MAX`, the largest scrap field) salvage next, so
  8,000 in space stays DEBRIS ×4 with ROC ×2 on the second line; above it
  ground first, so 76,000 → ROC ×19 (exact), DEBRIS ×38 (exact).
- Reader limits: `max_value` default 100,000 and `min_value` 2,000 (was
  2,500, which dropped a single salvage piece or plant) in `app/config.py`
  DEFAULTS and in `SignatureOCR`. Defaults only; existing settings files are
  not rewritten (unreleased program).
- Agricium stays at scmdb's 3,885 (grimhex says 3,895); the unmatched recorder
  will settle it.

### Feedback on every read

- The signature line is two labels. Left, `SCANNED SIGNATURE <n>`
  (`MiningPanel.set_scanned`): the number from every read, `—` when a read
  found no number (left unchanged when the read reports no plate or tracking
  is searching). Before, an unreadable crop was
  dropped silently in `_on_result` and a first unconfirmed read only showed
  "reading". Right, `MATCHED SIGNATURE <n>`, the signature of the shown
  result, or `MATCHED SIGNATURE —` with no match.
- `NN% MATCH` moves under the matched signature as `READ NN%` (OCR
  confidence), keeping its colours.
- A second exact match of another kind is shown on its own line,
  `or DEBRIS ×38` (76,000) / `or HARVESTABLES ×5` (10,000).
- Result border (`MiningPanel.set_result`): about `theme.px(3)`, green
  (`theme.GOOD`) for a confirmed exact match, yellow (`theme.AMBER`) for a
  confirmed reading with no exact match (a `~` guess counts as none), red
  (`theme.BAD`) for no read. The panel is 172 px high (was 158) for the extra
  rows. No colour (today's thin cyan edge) while a first
  read waits for confirmation and when the card goes lost (2 s after the last
  good read). Text, numbers and chips keep their colours.
- Red only while tracking reports the plate on screen (track state `locked`)
  and no number could be read for about 1 s in a row (`NOREAD_SECONDS` in
  `app/main.py`, `time.monotonic`), timed rather than
  counted in frames. Tracking off or no plate: never red. During red the
  matched side and ore name keep the last good result.

### Recorder for unmatched readings

- `app/unmatched.py`, `UnmatchedLog`: every confirmed reading without an exact
  match is saved under `%APPDATA%\SC Assistant\unmatched\` as a PNG of the
  crop plus an entry (`value`, `kind`, `time`, `image`) in `index.json`,
  written through `app.safe_store`. `kind` is `"unknown"` for now. The same
  value within 60 s is recorded
  once; the newest 200 entries are kept and older pictures deleted. An
  `index.json` that cannot be read is never saved over.
- Settings → *Unmatched readings*: `None saved` / `N saved`, the newest three
  rows (value, time), **OPEN FOLDER**, and **CLEAR** (two clicks; the first
  shows `CLEAR?` for 3 s). CLEAR deletes the pictures and `index.json`; the
  folder stays.
- Review: when the user comes back with missing scans, the folder
  (`index.json` and the pictures) is read together and the missing
  signatures are decided.

### Reset settings

- Settings → **RESET SETTINGS** (red, two clicks like QUIT; the first click
  shows `CLICK AGAIN TO RESET` for 3 s), in a new last section *Reset*.
- `config.reset_to_defaults()` copies the whole settings folder to a sibling
  `SC Assistant backup <YYYY-MM-DD HHMMSS>` (a ` (2)` suffix if it exists),
  then removes `config.json`/`config.tmp`, `anchor.png`, the caches
  (`hauling_*.json`, `routes_cache.json`, `where_to_mine.json`,
  `signatures_scmdb.json`), their `.bak` copies and the `unmatched` folder.
  Kept: `notes.txt`, `inventory.json`, `unlocked_blueprints.json`,
  `refinery_jobs.json`, `active_run.json`, `workflow_wallet.json`,
  `error.log`, their `.bak` files and anything unknown. The lists are the
  module constants `RESET_REMOVE` / `RESET_KEEP` (shell patterns). Removal is
  all or nothing: everything is first renamed into a staging folder, and a
  failed rename puts it back and raises.
- The app stops the scanner, swaps in a default config and stops saving it on
  quit (so restarting cannot write the old settings back), then restarts. If
  the reset fails nothing is removed, the scanner resumes and Settings shows
  `Reset failed, nothing was removed: <reason>`.

### Collapsible Settings sections

- The settings window is six groups, top to bottom: SCANNER (*Signature
  capture region*, *Scanning*), SCAN DATA (*Signature data*, *Unmatched
  readings*), HOTKEYS, LOOK & SOUND (*Appearance*, *Voice*), UPDATE & RESET
  (*Update*, *Reset*) and SUPPORT, which moved from the top to the bottom.
  The old section names stay as sub-headings inside a group of two.
- Each heading row (`▸` closed, `▾` open) opens or closes its group; any
  number can be open. A closed heading shows a grey summary on its right
  (monitor and `no box`/`box set`; `<N> ores · <M> unmatched`; SHOW BAR and
  HIDE ALL keys; UI scale and voice; `v<x> installed` or `v<x> available`),
  elided when long. The window resizes to fit after each change, inside its
  screen. Closing HOTKEYS cancels a pending key capture.
- The open groups are saved as `settings_open` in `config.json` (default
  `["scanner"]`; unknown ids are dropped). `SettingsPanel.SECTION_IDS`,
  `set_open_sections`, `open_sections`, `sections_changed` (user clicks only)
  and `set_force_open`.
- While no box is drawn SCANNER is held open (`set_force_open("scanner")`,
  released when a box is applied), and the first-run DRAW REGION pulse also
  holds it open; when the pulse ends SCANNER is left open. Widgets in a closed
  group still exist.

### Rename to SC Assistant, version 1.0.0

- One place for the names: `app/version.py` holds `APP_NAME`
  (`SC Assistant`), `EXE_NAME` (`SCAssistant`), `REPO`
  (`swill008/sc-assistant`), `MUTEX_NAME`, the release file names and the
  User-Agent. The nav bar brand reads `SC ASSISTANT`.
- Program `SCAssistant.exe`, built by `sc-assistant.spec`; installer
  `installer/sc_assistant.iss`. Release files `SCAssistant-<version>-Setup.exe`
  and `SCAssistant-windows-x64.zip`; the updater looks for these names.
- The installer keeps the same AppId, so it upgrades Citizen Assistant rather
  than adding a second program. It installs to
  `%LOCALAPPDATA%\Programs\SC Assistant` and removes the old Citizen Assistant
  program folder and Start menu entry once (one-time code). Its AppMutex lists
  the new and the old name, so a running Citizen Assistant is never
  overwritten.
- Settings folder `%APPDATA%\SC Assistant`. On first start
  `%APPDATA%\Citizen Assistant` is moved there once (one-time code); it never
  overwrites, and when both folders exist the new one is used.
- The GitHub repository moves from `swill008/citizen-assistant` to
  `swill008/sc-assistant`; GitHub redirects the old address.
- Version 1.0.0 is lower than 1.2.19, so an installed 1.2.19 never offers it
  under UPDATE: install 1.0.0 by hand once; updates work normally after that.
- The fork's v1.2.17 and v1.2.18 releases are withdrawn; their history stays
  below under *Earlier (1.2.x, as Citizen Assistant)*.

### Data safety

**What happened.** The code review of 2026-11-01
(`docs/reviews/2026-11-01-code-review.md`) found that a file which could not be
read (locked by another program, saved in another encoding, broken JSON) was
treated as empty, and the next save then replaced it.

**Change.** One shared store, `app/safe_store.py`, now reads and writes
`notes.txt`, `inventory.json`, the blueprint registry and the ore-finder cache:

- A file that cannot be read gives "not loaded", never an empty value. NOTES,
  INVENTORY and the blueprint registry then refuse to save over it for that
  session.
- NOTES shows `NOT LOADED` with the reason in the footer and the editor turns
  read-only. INVENTORY shows `NOT LOADED` and `FILE NOT LOADED` and does not
  allow adding, editing or deleting notes.
- Broken JSON is copied once to `<name>.bad-<time>` so it can be recovered by
  hand.
- Every save writes a temporary file and renames it over the old one; the
  previous file is kept as `<name>.bak`.
- Windows file locks are retried (5 tries, 0.1 s apart) before giving up.
- Text is read as UTF-8 (with or without a BOM) and falls back to
  Windows-1252, so a file saved by another editor still opens.
- The ore-finder cache is only a copy of the website, so a bad file or a bad
  entry is skipped and the next sync rewrites it.

### HUD tracking feedback

- The scanner header has a chip: `TRACKING` (cyan) when the pin is found,
  `SEARCHING` (amber) while it is lost, `FIXED BOX` (grey) when tracking is off.
- SHOW BOX outlines both the pin and the digits, with a label above them:
  `TRACKING ✓  42,000`, `SEARCHING…` (where the plate was last seen) or
  `FIXED BOX`.
- After DRAW REGION the result is shown on screen for 3 seconds, even with
  SHOW BOX off: `PIN FOUND — TRACKING ON` or `NO PIN FOUND — FIXED BOX`.
- The mining panel is 372 px wide instead of 330, to fit the chip and the pin.

### Tracking after an upgrade or a resolution change

- A box with no saved pin (drawn before pins existed, or after the pin was
  dropped) learns it once, from the first exact signature the fixed box reads;
  the region note then says `Pin learned from the scan: tracking is on.`
- A box moved to a monitor with a different height drops the pin, and the pin
  is learned again the same way. A monitor that only moved (or is wider at the
  same height) keeps it.
- Calibration errors other than "no pin" are now named in the note, and a
  missing `anchor.png` clears the saved pin details.

### Signature data from scmdb.net

- The ship ores and the ground mineral lists now come from
  [scmdb.net](https://scmdb.net) game data (`versions.json`, then
  `mining_data-<version>.json`), in a background thread at most once a day,
  cached as `signatures_scmdb.json`. The bundled `app/data/signatures.json` is
  the fallback. `signature_channel` picks `live` (default) or `ptu`;
  `signature_source: "bundled"` never downloads (`app/sigsource.py`).
- Ground readings name their minerals: 3,000-type readings show
  `HAND MINING · …` (8 minerals), 4,000-type readings `ROC · …` (22); the
  tooltip lists them all. The bundled file has both lists.
- Settings → *Signature data* says where the table came from, for example
  `scmdb 4.10.2 live` or `bundled 4.10.2 (scmdb unavailable: …)`.
- Checked 2026-11-01: the bundled ship bases and both ground lists equal scmdb
  `4.10.2-live.12913470` (and `4.10.3-ptu.13055118`).

### Release notes

- Each version gets `release-notes/<version>.md`, starting
  `## What's new in <version>` (see `release-notes/README.md`).
  `tools/release_body.py` turns it into the GitHub release text with a
  "How to install" section; the release workflow stops when the file is
  missing or its heading is wrong. The release text no longer comes from this
  file.
- Settings → *Update* shows "What's new in vX" under CHECK when a newer
  version exists, as plain text only.

### Update fixes

- The downloaded Setup is checked against GitHub's SHA-256 digest (and its
  size and EXE header); a mismatch deletes it.
- Settings names the version actually downloaded, which can be newer than the
  one CHECK saw.
- The hand-off waits for the old app to exit with no time limit (it was 60 s),
  and the button stays off while it runs.
- If Setup exits with code 1 (could not start) or 2 (stopped before
  installing), the old version is started again.
- Quitting during a download cancels it and waits for the update thread.

### Scanner fixes

- The TRACKING slider moves in whole 50 px steps and saves once, when it is
  released, instead of on every pixel of a drag.
- The saved pin picture is decoded on the scanner thread after the windows
  appear, not on the GUI thread at start-up.
- SHOW BOX moves with one placement on the same monitor, and its correction
  loop is bounded.

### Quality of life

- **Hotkeys.** Settings → *Hotkeys* rebinds SHOW BAR (F3) and HIDE ALL (F4) and
  can give each tool (MINING, ORE FINDER, HAULING, UEX, INVENTORY, COMBAT,
  NOTES) a key that toggles it. Click a key, then press the new one; Esc means
  no key; a key already in use is refused. Saved as `hotkey_toggle_nav`,
  `hotkey_panic` and `hotkey_tools`; applied without a restart.
- **Window pins.** Every panel, and the settings window, has a push-pin next to
  its `✕`. A pinned panel stays on screen when everything is hidden (F4 or the
  nav bar's `✕`); a pinned scanner keeps its SHOW BOX outline. Saved as
  `pinned_windows`.
- **Data age.** COMBAT shows `LIVE` while `Game.log` was written in the last
  2 minutes, otherwise `IDLE · last event 5 min ago`. HAULING shows
  `UPDATED 5 MIN AGO` and turns to an amber `STALE` once the data is older than
  its cache lifetime. ORE FINDER shows `SYNCED 5 MIN AGO` (or `NOT SYNCED`) and
  `STALE` after 15 minutes.
- **DRAW REGION.** Right-click cancels, like Esc. Releasing the drag with Ctrl
  held keeps the box for fine-tuning: arrow keys move it 1 physical pixel
  (Shift: 10), Ctrl+arrows resize it, Enter confirms, Esc or right-click
  cancels. On monitors at 200% scale or more a magnifier follows the cursor.
  Mouse moves repaint only what changed.
- **First run.** With no box yet, `⚙` on the nav bar and DRAW REGION in
  Settings pulse until one is drawn.

### Tests

New, each printing PASS/FAIL lines with the number of failures as exit code:

- `tools/datasafety_selftest.py`: locked, Windows-1252 and broken files, and
  cache entries with unknown fields, for all four stores; the file must not be
  overwritten (bytes compared), a save keeps a `.bak`, a short lock is
  retried. `--old` runs the same checks on HEAD's files.
- `tools/overlay_selftest.py`: SHOW BOX marks, the scanner chip and pin, the
  picker conveniences and the `⚙` pulse (needs a desktop; windows invisible,
  on a secondary monitor).
- `tools/signature_selftest.py`: scmdb conversion, ground lists, cache and
  fallback; `--live` adds a real read-only fetch.
- `tools/hotkeys_selftest.py`: rebinding while the hotkey thread runs and the
  Settings rows, with a fake `user32` (no real hotkey is registered).
- `tools/dataage_selftest.py`: data age and window pins on HAULING, ORE FINDER,
  COMBAT and UEX, offline.
- `tools/release_notes_selftest.py`: `tools/release_body.py` and both
  workflows; with `RELEASE_CHECK=1` (the release workflow sets it) it fails
  when `app/version.py` names a version without a notes file. The build
  workflow runs it on every push.

- `tools/nextdata_selftest.py`: scan limits against scmdb's
  `clusteringPresets` (fixture `tools/fixtures/scmdb_clusters_4.10.2-live.json`;
  `--live` fetches the newest data), harvestables, the 100,000 reader limit,
  the unmatched recorder and `reset_to_defaults`.
- `tools/panel_selftest.py`: SCANNED / MATCHED SIGNATURE, `READ NN%`, the
  second line and the result border, and the card layout at UI scale 1.0 and
  1.5.
- `tools/settings_extra_selftest.py`: RESET SETTINGS and UNMATCHED READINGS
  with real clicks (two-click buttons, error note, list, layout at 1.0 and
  1.5).

Extended: `tools/update_selftest.py` (digest check, "What's new", the
hand-off command run against a fake Setup, the TRACKING slider),
`tools/scan_selftest.py`, `tools/scan_e2e_selftest.py` and
`tools/settings_persist_selftest.py`.

## Earlier (1.2.x, as Citizen Assistant)

### v1.2.19 — 2026-11-01

The scanner follows the signature plate as the HUD sways in flight.

#### New: HUD tracking

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

#### Tests

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

#### Known limits

- The OCR sometimes drops a zero on a blurred 80,000 plate and reads 8,000,
  which is a valid signature (debris ×4). 80,000 itself is above the 60,000
  limit and correctly ignored. Not changed in this release.
- Very heavy scan tint can turn a 5 into a 6 (one labelled frame).

### v1.2.18 — 2026-11-01

Adds a Windows installer next to the standalone download. The program itself
is unchanged from v1.2.17 (see below for its fixes).

#### New: installer

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

#### Release and build workflows

- Releases publish both downloads; a tag push releases automatically (Actions
  is now enabled on this fork), and a release can also be run by hand for an
  existing tag.
- Every push to `main` runs the headless self-tests and builds both downloads
  as a test artifact.
- The release text comes from this file.

#### Tests

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

### v1.2.17 — 2026-11-01

Fixes for 5K2K and mixed-scaling desks, and for game stutter while the scanner
runs; new scanner settings; a QUIT button; updates now come from this fork.
Measured on Windows 11, Ryzen 7 9800X3D (8 cores, SMT off), RTX 4090, main
monitor 5120×2160 at 150% beside two 1920×1080 at 125% and a 3840×2160 TV at
300%.

#### Fixed: the scanner read nothing on a 5K2K screen

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

#### Fixed: frame hitches while the scanner runs

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

#### New: scanner settings for resolution, scaling and read rate

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

#### New: QUIT on the nav bar

`✕` only hides the overlay; QUIT ends it. One click arms it (red, `QUIT?`), a
second within 2.5 s quits; otherwise it disarms.

#### Changed: updates come from this fork

`app/updater.py` pointed at `fishtaco7/citizen-assistant`, so UPDATE in this
fork would have replaced its fixes with the upstream code. CHECK and UPDATE now
use `swill008/citizen-assistant`; the HTTP User-Agent names the fork. Nothing
updates by itself.

#### Tests

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

#### Known limits

- A box moved for a new resolution or aspect ratio is a best estimate of where
  the HUD went; check SHOW BOX or SHOW PREVIEW and press SELECT if it is off.
- Any overlay window over the game, SHOW BOX included, makes Windows composite
  the game's frames (measured: 60.6 → 69.7 FPS with every overlay window
  hidden). Not changed in this release.
