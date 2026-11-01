# SC Assistant

A small Star Citizen overlay. Press **F3** for a nav bar at the top of the screen;
the first tool is a **mining scanner** that reads the signature number from the
scan HUD and tells you what the rock is.

The scanner and ore finder use screen capture + OCR; the hauling tools use
read-only public HTTP APIs. The combat tracker tails `Game.log` for damage,
kills and soft deaths and feeds the **COMBAT** tab. The headless
blueprint/inventory tracker tails the same log for blueprint unlocks and item
acquisitions, then publishes structured events to the host overlay. Nothing
reads game memory, injects code, or synthesises input.

SC Assistant was called **Citizen Assistant** until v1.2.19; v1.0.1 is the
first published release under the new name (see *Upgrading from Citizen Assistant
1.2.x*). It started as a fork of
[fishtaco7/citizen-assistant](https://github.com/fishtaco7/citizen-assistant).

---

## Requirements

- Windows 10/11, Star Citizen running **borderless / windowed fullscreen**
  (exclusive fullscreen cannot be captured or overlaid reliably)
- Python 3.11+ (built and tested against 3.13)

### macOS (UI preview only)

The panels, theme, network tools and scanner can run on a Mac for development.
A small platform layer (`app\win32.py`, `app\hotkeys.py`, `app\config.py`)
swaps the Win32 calls for Qt equivalents. What is different:

| Feature | macOS preview |
| --- | --- |
| Nav bar, scanner, ore finder, HAULING, INVENTORY, COMBAT, settings | Work |
| `--demo` synthetic signature | Works (OCR included) |
| Spoken ore announcements | Work (AVSpeechSynthesizer) |
| Screen capture of a game | Not applicable — Star Citizen is Windows-only |
| Capture exclusion (`WDA_EXCLUDEFROMCAPTURE`) | No-op, windows appear in screenshots |
| F3 / F4 | Application shortcuts: only while an overlay window has focus. Use the tray menu otherwise |
| Config location | `~/Library/Application Support/SC Assistant/` |

Setup without Homebrew, using [uv](https://astral.sh/uv):

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh
uv python install 3.13
uv venv --python 3.13 .venv
uv pip install --python .venv/bin/python -r requirements.txt
./run.command                     # demo mode
./run.command --open hauling      # start with a tool open
```

`run.command` passes any arguments straight to `app`, and defaults to `--demo`
so no capture region is needed. The Windows launchers are unaffected.

## Install

### One-click install (Windows)

Run **`install.bat`** from the folder you want to use. It sets up `C:\scov` (if
needed), installs the requirements, creates a **SC Assistant** shortcut on the
desktop and in the Start menu, removes shortcuts left behind by a previous install,
and asks whether it should start with Windows.

The shortcuts launch `pythonw.exe launcher.py` by absolute path, so **no console
window is ever shown** and the shortcut always runs the copy it was created from.
`run-hidden.vbs` does the same thing straight from the folder.

Only one copy runs at a time. Launching a second copy shows a short notice
instead of opening a duplicate overlay, because the extra copy could not
register the global F3/F4 hotkeys and would look like they had stopped working.

`uninstall.bat` removes the desktop / Start menu / startup shortcuts; your
settings and the `C:\scov` environment are left alone.

Because `pythonw.exe` has no console, unhandled errors are appended to
`%APPDATA%\SC Assistant\error.log` — check that file if the overlay stops starting.

### Checking which build is running

Every copy stamps its build in `⚙` next to the title, and on the command line:

```bat
C:\scov\Scripts\python.exe -m app --version
```

Windows keeps shortcuts forever. After downloading a new copy, run `install.bat`
**from the new folder**: it rewrites the desktop and Start menu shortcuts to point
at that folder, and deletes any left behind by a previous install, so Start menu
search can no longer launch the old one. Shortcuts now call `launcher.py` by
absolute path, so the copy that runs is the one next to the shortcut's folder
rather than whatever happens to be the working directory.

Settings and notes from an older `SC-Overlay` folder (`config.json`,
`inventory.json`, `unlocked_blueprints.json`) are copied into the new
`SC Assistant` folder automatically on first run, so the region
calibration and stash notes carry over.

### Prebuilt EXE: installer or standalone

Each [release](https://github.com/swill008/sc-assistant/releases) has two
downloads with the same program inside:

| Download | What it is |
| --- | --- |
| **SCAssistant-X.Y.Z-Setup.exe** | Installer. Installs for your Windows user only (no administrator rights) into `%LOCALAPPDATA%\Programs\SC Assistant` by default, adds a Start menu entry and an uninstaller (also under *Settings → Apps*), and optionally a desktop shortcut and *Start when Windows starts*. Running a newer Setup installs over the old version. |
| **SCAssistant-windows-x64.zip** | Standalone. Unzip anywhere and run `SCAssistant.exe`; nothing is installed. Keep the folder intact: the program needs the files next to it. |

Settings, notes and caches live in `%APPDATA%\SC Assistant` for both, so
they carry over between versions and between the two kinds; installing,
updating or uninstalling never touches them.

**Updating with the installer.** Quit SC Assistant (QUIT on the nav bar)
and run the new Setup. It moves the old program files aside first and deletes
them only once the new ones are in; if anything fails, or the program is still
running, it puts the old version back and says so, so the version that worked
still starts. (`installer/sc_assistant.iss`, same design as the
Gremlin-Platforms installer.)

An installed copy can also update itself from `⚙` → **UPDATE**, which
downloads the new Setup and runs it (see *Settings window*).

**Updating the standalone.** Unzip the new release to a new folder (or over the
old one after quitting it). A running `.exe` cannot replace its own files, so
in a standalone copy **UPDATE** only opens the Releases page.

Both are unsigned, so SmartScreen warns on first run — choose **More info →
Run anyway**.

Releases are produced by `.github/workflows/release.yml` when a `v*` tag is
pushed, or by hand for an existing tag (Actions → *Release Windows EXE* → *Run
workflow*, or `gh workflow run release.yml -f tag=v1.0.0`); a fork does not
run push-triggered workflows until Actions has been enabled for it once, and a
manual run works regardless. The job fails if the tag does not match `VERSION`
in `app/version.py`, runs the headless self-tests before building, and uses
`release-notes/<version>.md` plus a "How to install" section as the release
text (`tools/release_body.py`, followed by GitHub's generated notes); it stops
before building when that file is missing or does not start with
`## What's new in <version>`. It publishes the standalone zip and the installer.
`tools.scan_selftest` and `tools.scan_e2e_selftest` need real monitors, so run
them locally before tagging.
Pushes to `main` also build both under **Actions** as a test artifact, but those
expire after 30 days and need a GitHub login.

The build runs PyInstaller on `windows-latest` with the pinned versions from
`requirements-lock.txt`. `sc-assistant.spec` bundles `app/data` and
`app.ico`, and collects the OCR runtime that `app/ocr.py` imports lazily.

To build locally on Windows:

```bat
py -3.13 -m pip install -r requirements-lock.txt pyinstaller
py -3.13 -m PyInstaller --noconfirm --clean sc-assistant.spec
powershell -File installer\build_installer.ps1
powershell -File installer\test_installer.ps1 -Setup dist\SCAssistant-X.Y.Z-Setup.exe
```

`build_installer.ps1` needs [Inno Setup 6](https://jrsoftware.org/isinfo.php)
and writes `dist\SCAssistant-X.Y.Z-Setup.exe` (version from
`app/version.py`). Keep the repository in a short path: the deepest bundled
file is about 110 characters, and Windows' 260-character path limit makes the
build fail from a deep folder. `test_installer.ps1` installs into a throwaway
folder silently and checks a fresh install, that the program starts (skipped
while another copy is running), an upgrade, an upgrade refused while the
program's files are in use with the old version put back, the uninstall, and
that `%APPDATA%\SC Assistant` is unchanged.

The result is `dist\SCAssistant\SCAssistant.exe`.

### Upgrading from Citizen Assistant 1.2.x

Install 1.0.1 **by hand once**: download `SCAssistant-1.0.1-Setup.exe` from the
[releases](https://github.com/swill008/sc-assistant/releases), quit Citizen
Assistant and run it. The version number started again at 1.0 with the new
name, which is lower than 1.2.19, so the old **UPDATE** button never offers it.
From 1.0.1 on, **UPDATE** works as usual.

What happens on the way:

- The installer upgrades the same program (same AppId), now in
  `%LOCALAPPDATA%\Programs\SC Assistant`. It removes the old
  `Citizen Assistant` program folder and its Start menu entry, once.
- On its first start SC Assistant moves `%APPDATA%\Citizen Assistant` to
  `%APPDATA%\SC Assistant`, once. It never overwrites: if both folders exist,
  the new one is used and the old one is left where it is.
- Your settings, notes, inventory and blueprint registry are never deleted.

### Manual install

PySide6 pulls in very deep paths, so use a short install location — `C:\scov` is
what the launchers look for:

```bat
py -3.13 -m venv C:\scov
C:\scov\Scripts\python.exe -m pip install --upgrade pip
C:\scov\Scripts\python.exe -m pip install -r requirements.txt
```

`setup.bat` runs exactly those three steps, which is the quickest way to set up a
second machine.

`requirements.txt` installs `PySide6-Essentials` + `PySide6-Addons` instead of
the full `PySide6` meta-package, so Qt WebEngine and Qt PDF are not downloaded
(several hundred MB saved). The overlay only needs Qt Core/GUI/Widgets and
QtTextToSpeech.

If you install the venv somewhere else (for example `.venv` next to this file),
`run.bat` will find it — the search order is `C:\scov`, then `.venv`, then
whatever `pythonw` is on `PATH`.

## Continue on another PC

Everything needed to build and run is in this folder — no database, no compiled
artifacts. Copy it over (or clone a private repo) and rebuild the venv:

1. Install **Python 3.13 (64-bit)**. The python.org build is the least
   surprising; the Microsoft Store build also works (this project was built on
   it), but it redirects `%APPDATA%` and trips the 260-character path limit when
   PySide6 is installed in a deep folder.
2. Get the folder onto the new PC — it already lives in OneDrive, so it may sync
   by itself; otherwise copy it or clone it. Skip `.venv`, `__pycache__`,
   `.DS_Store` and `tools\preview_out`; they are machine-specific or
   regenerated. A source-only `sc-assistant-windows.zip` is the easiest way to
   move it without the macOS virtualenv.
3. Run `install.bat` (or `setup.bat` if you only want the environment). It
   creates `C:\scov` and installs `requirements.txt`, then adds the shortcuts.
   For the exact versions this build was tested with, install
   `requirements-lock.txt` instead.
4. Launch the overlay from the **SC Assistant** shortcut (or `run-hidden.vbs`);
   both pick up `C:\scov` or a local `.venv` on their own and show no console.

Not everything lives in the folder:

| What | Where it lives | On the new PC |
| --- | --- | --- |
| Capture region, panel positions, hotkey prefs | `%APPDATA%\SC Assistant\config.json` | Don't copy it — press **DRAW REGION** in Settings once on the new PC |
| Ore location cache | `%APPDATA%\SC Assistant\where_to_mine.json` | Re-downloaded from scminer.rocks |
| Inventory stash notes | `%APPDATA%\SC Assistant\inventory.json` | Manual notes — copy this file to keep them |
| Blueprint + inventory registry | `%APPDATA%\SC Assistant\unlocked_blueprints.json` | Permanent unlock history — copy this file to keep it |
| Planner route cache | `%APPDATA%\SC Assistant\routes_cache.json` | Rebuilt on demand; delete it to force a full UEX sync |
| OCR models | inside the `rapidocr-onnxruntime` wheel | Reinstalled with the deps |
| Signature database | `app\data\signatures.json` | Travels with the code |

Panel positions are per-machine, so expect to place the scanner, ore finder and
inventory panel once after calibrating.

Git is the easiest way to keep two machines in sync:

```bat
git init
git add .
git commit -m "SC Assistant"
```

`.gitignore` already excludes the venv, `__pycache__` and `tools\preview_out`,
so nothing machine-specific ends up in the repo. Push to a private remote and
pull on the other PC, then run `setup.bat` once there.

## Run

```bat
run.bat
```

`run-hidden.vbs` starts the same command with no console flash at all. Double-
click it, or make a shortcut to `C:\scov\Scripts\pythonw.exe` with arguments
`-m app` and “Start in” set to this folder. Some managed PCs block VBScript; in
that case use `run.bat` or the shortcut.

`run-debug.bat` keeps a console open and prints scan results, which is what you
want if something looks wrong.

Starting the app with no saved region (first run, or after deleting
`%APPDATA%\SC Assistant\config.json`) does not open the region picker by
itself: the scanner panel says `No capture region — press DRAW REGION in
Settings (⚙)`, and you draw the box when the scan readout is on screen. The
scanner loads OpenCV and the OCR model only after a region exists, so the window
opens faster; the first scan after calibration may take a moment while they
load on the scanner thread.

### Windows notes

- `run.bat`, `run-hidden.vbs` and the in-app **RESTART** button all start the app
  with `pythonw`, so no console window appears — and the helpers that talk to
  PowerShell (refinery speech, WAV playback) pass `CREATE_NO_WINDOW` for the
  same reason.
- `Game.log` is looked for in the RSI launcher's default
  `…\Roberts Space Industries\StarCitizen\LIVE\Game.log`, the same layout under
  `Program Files`, `Program Files (x86)` and `C:\Games`, and under
  `StarCitizen`, `Roberts Space Industries\StarCitizen` and `Games\StarCitizen`
  on every fixed drive. `LIVE`, `PTU`, `EPTU` and `HOTFIX` are all checked. Set
  `SC_GAME_LOG` to a full path to override the search.
- The overlay windows are marked `WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW`, so they
  never steal focus from the game. They are **visible in screenshots and
  streams by default**; `⚙` → the **HIDDEN** button hides them from capture
  (OBS, the game's own screenshots) when you want that instead.
- The OCR path needs `opencv-python` and `rapidocr-onnxruntime` from
  `requirements.txt`. `setup.bat` installs both into `C:\scov`.

## Controls

| Key / control | Action |
| --- | --- |
| **F3** | Show / hide the nav bar |
| **F4** | Hide everything except pinned panels (panic key) |
| **QUIT** on the nav bar | Quit the overlay: click once to arm (it turns red and reads `QUIT?`), again within 2.5 s to quit. `✕` only hides it. |
| drag a panel header | Move that window |
| push-pin next to a panel's `✕` | Pin the panel: it stays on screen when F4 or the nav bar's `✕` hides everything else |
| `⚙` on the nav bar | Open settings |
| `MINING` on the nav bar | Show / hide the scanner |
| `ORE FINDER` on the nav bar | Show / hide ore locations |
| `HAULING` on the nav bar | Show / hide trade routes and hauling contracts |
| `INVENTORY` on the nav bar | Show / hide manual stash notes |
| `COMBAT` on the nav bar | Show / hide the live Game.log combat feed |
| `NOTES` on the nav bar | Show / hide the notepad |
| tray icon | Show the bar, quit |

> On macOS, F3/F4 are application shortcuts — they work while one of the
> overlay windows has focus. The tray menu always works.

F3 and F4 are the defaults. `⚙` → *Hotkeys* changes them and can give each tool
its own key, which toggles it like its nav-bar button (see *Settings window*).
The keys are delivered two ways: `RegisterHotKey` for the normal case, and a
25 ms `GetAsyncKeyState` poll for games that stop delivering hotkeys while
exclusive fullscreen owns the display. If they still do nothing in a particular
game, run it borderless / windowed fullscreen rather than exclusive.

The nav bar remembers whether it was open and the scanner remembers where you
dragged it. Pinned panels are remembered too (`pinned_windows` in
`config.json`). A pinned scanner keeps reading while everything else is
hidden, and keeps its SHOW BOX outline.

The **combat tracker** runs automatically in the background and feeds the
`COMBAT` tab. The tracker itself stays headless; the panel renders events from
the `OverlayApp.combat_event` Qt signal. Other hosts can consume the same
payloads through the tracker's thread-safe queue.

## Calibrating the scanner

The scanner needs to know where the signature number appears on your screen.

1. Open the SC mining scan HUD so a signature number is visible.
2. In `⚙` → *Signature capture region*, check **MONITOR** shows the monitor the
   game is on (it lists every monitor with its real resolution and Windows
   scaling, read from Windows — nothing to type in).
3. Click **DRAW REGION**. The picker opens on that monitor. On the first run,
   before any box exists, `⚙` on the nav bar and DRAW REGION pulse to show
   where to start.
4. Drag a box **tightly around the digits only** (a little padding is fine, but
   do not include the word "SIGNATURE" or the units). Releasing the mouse
   confirms the box. Right-click or Esc cancels.
5. For 3 seconds the result is drawn on screen, even with SHOW BOX off:
   `PIN FOUND — TRACKING ON` around the pin and the digits, or
   `NO PIN FOUND — FIXED BOX` (see *tracking* below).
6. Optional: **SHOW BOX** (in *Scanning*) draws the box on screen so you can
   see exactly where the scanner reads; **SHOW PREVIEW** shows the pixels it
   reads. Turn SHOW BOX off again when you are done (see *Game performance*).

**Fine-tuning the box.** Hold Ctrl while releasing the drag and the box stays
on screen instead of being used at once: the arrow keys move it 1 physical
pixel (Shift: 10), Ctrl+arrows resize it from the right and bottom edges,
Enter confirms it, and Esc or right-click cancels. A new drag starts over. On
monitors at 200% scale or more a magnifier follows the cursor, showing the
screen as it was when the picker opened, one physical pixel per cell.

A good box is roughly 200 × 50 physical pixels at 1440p; on a 5120 × 2160
(5K2K) screen the signature digits themselves are only about 60 × 26, so a box
of about 80 × 40 is plenty. The label beside the box shows its size in physical
pixels while you drag. The region is stored in physical pixels, so it stays
correct if you change display scaling later.

**Several monitors with different scaling** (for example a 5K2K main screen at
150% beside a TV at 300%) are supported: the picker opens one dimmed window per
monitor, each at that monitor's own scale, and the stored box is taken from the
physical mouse position (`GetPhysicalCursorPos`), so it is exactly the box you
dragged. Builds before this fix used one window stretched over every monitor;
Qt gave it a single scale (whichever monitor it landed on), so on a mixed-scale
desk the box was stored at the wrong size — on a 150% main screen next to a
300% TV, half the width and height — and OCR read nothing. If you calibrated
with an older build, press **DRAW REGION** once more.

**Changing resolution or monitor later.** When you draw the box, the app also
records that monitor's resolution and position. If they change afterwards (a
new resolution, a different monitor, a rearranged desktop), the box is moved to
match on the next start or as soon as Windows reports the change, and
*Signature capture region* shows an amber note such as
`Monitor changed (5120×2160 → 3840×1600): box adjusted to match`. Choosing a
different **MONITOR** moves the box the same way. Star Citizen scales its HUD
with the vertical resolution and keeps it centred, so the box keeps its offset
from the screen centre and both are scaled by the height ratio
(`app/display.py`, `rescale`); for the same aspect ratio that is plain
proportional scaling. Check SHOW BOX or SHOW PREVIEW afterwards, and press
**DRAW REGION** if the HUD sits somewhere else. Changing only Windows scaling needs
nothing: the box is stored in physical pixels, which scaling does not change.
If the monitor's height changed, the saved pin is dropped (the HUD, and the
pin with it, is drawn at a different size) and HUD tracking turns off; it
turns back on by itself the next time the box reads a signature (see below),
or press **DRAW REGION**. A monitor that only moved, or a wider one at the same
height, keeps its pin.

**Following the HUD as it sways (tracking).** In flight Star Citizen's HUD
moves with the ship's "physics" — on a 5120×2160 screen the signature plate
was measured moving 218 px left to 250 px right and 43 px up to 227 px down
around the drawn box, often 100 px within a tenth of a second, so a fixed box
caught it in 19 of 300 frames. When you press **DRAW REGION** with the scan readout
on screen, the app also saves the plate's orange **pin icon** just left of the
digits (`%APPDATA%\SC Assistant\anchor.png`). Each read then captures a
larger area around the box, finds the pin in it (about 1.3 ms; it searches a
quarter-size orange-only copy, then checks the best few spots at full size)
and reads the digits at their fixed place right of the pin. On the same
recording that read 259 of 300 frames, and when no plate is on screen the OCR
is not run at all. The pin is the anchor because it looks the same in every
ship, whatever the rest of the HUD looks like. **TRACKING** in *Scanning* sets
how far it searches (default ±400 px across and ±300 px up and down on a
2160-px-high screen, scaled for other heights); `OFF` reads the fixed box as
before. If DRAW REGION finds no pin next to the box, an amber note says tracking is
off — press DRAW REGION again with the readout showing.

A box without a saved pin (drawn with a build from before pins existed, or
after a height change dropped it) learns the pin by itself, once, from the
first exact signature the fixed box reads: the plate is on the box at that
moment. The note under *Signature capture region* then reads
`Pin learned from the scan: tracking is on.`

The chip in the scanner's header always shows the state: `TRACKING` (cyan)
while the pin is found, `SEARCHING` (amber) while it is lost, and `FIXED BOX`
(grey) when tracking is off. With **SHOW BOX** on, the outline goes around the
pin and the digits being read, with a label above them: `TRACKING ✓  42,000`,
`SEARCHING…` (drawn where the plate was last seen), or `FIXED BOX`.

The scanner reads that box **4 times a second** by default (`⚙` → *Scanning* →
**READS / S**, 1–8) and ignores frames that have not changed. A
high-confidence exact signature locks on the first read; fuzzy or less certain
reads still require two identical results before they are shown.

## Reading the scanner

```
● MINING SCANNER                  TRACKING  LOCKED
SCANNED SIGNATURE                MATCHED SIGNATURE
76,000                                      76,000
                                          READ 98%
ROC DEPOSIT                                   ×19
ROC · Agricium / Aluminum / ...
or DEBRIS ×38
```

- **TRACKING** — the HUD-tracking chip (`TRACKING`, `SEARCHING` or
  `FIXED BOX`; see *Calibrating the scanner*).
- **SCANNED SIGNATURE** (left, number under the caption) — the number from the latest read, updated on
  every read, also one that is not confirmed yet or matches nothing. `—`
  means the last read found no number (with tracking on: the plate is on
  screen but its number could not be read). Nothing changes while tracking
  sees no plate.
- **MATCHED SIGNATURE** (right) — the signature of the result shown below it.
  `—` under it means the number matched nothing in the table.
- **READ 98%** — how sure the text reader (OCR) is of the digits, not how sure
  the match is. It used to say `NN% MATCH`.
- **ROC DEPOSIT ×19** — what was matched and how many: here 19 ROC deposits
  (76,000 = 19 × 4,000; this one was a Feynmaline field). A ship rock names
  its ore: 10,710 = 3 × 3,570 is `BORASE ×3`.
- Ground deposits only tell you their size, so the detail line lists the
  minerals that can give that reading: `HAND MINING · Aphorite / Carinite / …`
  for 3,000-type readings and `ROC · Agricium / Aluminum / …` for 4,000-type
  readings. The line is cut to the panel width; the tooltip lists them all.
  Which one it is depends on where you are.
- **DEBRIS ×2** — salvage: exterior hull panels and scrap metal from wrecks
  read as clean multiples of 2,000 (2,000, 4,000, 6,000, 8,000 …), up to 50
  pieces. A large wreck goes well past a 10-rock cluster, so `22,000` is
  `DEBRIS ×11` rather than an ore.
- **Second line** — when a number is an exact match for two kinds, the second
  one gets its own line under the detail line: `or DEBRIS ×38` under a 76,000
  ROC reading, `or HARVESTABLES ×5` under a 10,000 `DEBRIS ×5` reading.
  Harvestable plants also read as multiples of 2,000 (1-10 plants).
- A leading `~` (`~QUANTANIUM`) means the number is *near* that ore's signature
  but not an exact multiple of it — a hint from OCR jitter, never a lock, and
  never spoken.
- A number already on screen is only replaced after two identical reads, so OCR
  alternating between two readings (for example `8,000` and a stray leading
  digit giving `28,000`) cannot make the panel flip back and forth. The first
  lock is still immediate.
- If the reading keeps flickering, the crop is probably catching a digit from a
  neighbouring HUD element; re-calibrate with a tighter box around the digits.
- The second line is the rarity and the secondary ores for that signature.
- No known signature at that exact number shows `UNKNOWN` plus the closest
  table entry, so a single misread digit is obvious instead of misleading.

When the number leaves the screen the last reading stays visible but dims.

### Result border

Text, numbers and chips keep their usual colours (ore names use their rarity
colour). The result is shown by the card's border instead, about 3 px thick at
100% scale:

| Border | Means |
| --- | --- |
| Green | A confirmed reading with an exact match. |
| Yellow | A confirmed reading with no exact match (a `~` near-guess counts as no match). |
| Red | The scan plate is on screen, but its number could not be read for about a second in a row. |
| Thin cyan (the usual edge) | Nothing to judge: a first read waiting for confirmation, or the card has dimmed (2 s after the last good read). |

Red only shows while tracking has found the plate on screen. With tracking off
(`FIXED BOX`) or no plate on screen the border is never red, and a single
dropped frame does not turn it red. While it is red the left side reads
`SCANNED SIGNATURE —`, and the matched side and the ore name keep the last good
result. A number above 100,000 counts as unreadable.

### Scan limits

Each kind of scan is matched up to its largest real group, taken from the game
data (scmdb.net 4.10.2 live clustering presets, and the Star Citizen Wiki):

| Kind | Signature per item | Items |
| --- | --- | --- |
| Ship mining rock | the ore's base, e.g. Borase 3,570 | 1-10 |
| ROC (ground vehicle) deposit | 4,000 | 1-25 |
| Hand mining (FPS) deposit | 3,000 | 1-21 |
| Salvage debris | 2,000 | 1-50 |
| Harvestables (plants) | 2,000 | 1-10 |

Why: a Feynmaline ROC field of 19 deposits reads 76,000. Before this the
reader dropped every number over 60,000 and the matcher stopped at 8 ground
deposits, so that scan showed nothing. The reader now accepts up to 100,000
(the largest real reading), and the limits above cover every group size the
game data lists (ROC fields 10-25 deposits, hand mining 10-21, ship rocks up
to 6, salvage scrap up to 15, harvestables 2-10). A test compares the limits
with scmdb's data.

### Unmatched readings

Every confirmed reading with no exact match is saved, so missing signatures
can be added later: the number, the time, the kind of scan (`unknown` for
now: the app cannot yet tell ship, ground or salvage scans apart) and a small
picture of the box, in `%APPDATA%\SC Assistant\unmatched\` (`index.json` plus one PNG
per reading). The same number within 60 seconds is saved once, and the newest
200 are kept. `⚙` → *Unmatched readings* lists them (see *Settings window*).

To review them: press **OPEN FOLDER**, compare each picture with its number in
`index.json` (a misread digit shows in the picture), and report the real ones
as an issue with the number and where you scanned it. **CLEAR** (click twice)
empties the list.

Leaving the pilot seat closes the scanner. The overlay reads the same
`Game.log` notification the hauling workflow uses (`Exited pilot seat`), so the
panel disappears when you stand up without anything touching the game. Set
`close_scanner_on_seat_exit` to `false` in `config.json` to keep it open.

### Voice

The scanner can say the result out loud. When a signature locks it announces the
ore and the number of rocks:

```
7,200 -> "Bexalite, times 2"
10,710 -> "Borase, times 3"
3,585 -> "Gold"
6,000 -> "Debris, times 3"
```

- Only **exact** signature matches are spoken. A fuzzy match is usually an OCR
  misread, and saying the wrong ore is worse than saying nothing.
- Each rock is announced once. Re-reading the same signature, a one-digit OCR
  jitter, or the scan HUD dropping and re-acquiring the same rock does not repeat
  the announcement. A genuinely different signature (a new rock) still speaks,
  even when it is the same ore. The remembered rock is only forgotten after
  `voice_idle_reset_seconds` (default `12`) without a scan, or when pausing and
  resuming.
- `⚙` → **Voice** has an **ON/OFF** button and a volume slider; the choice is
  saved as `voice_enabled` and `voice_volume` (0.0–1.0).

Speech uses QtTextToSpeech — SAPI on Windows, AVSpeechSynthesizer on macOS. If no
speech engine is installed the VOICE button says so in its tooltip and the
scanner keeps working silently.

## Refinery work orders (headless)

`app/refinery.py` is a separate, windowless tracker for refinery work orders. It
does not create widgets, resize the scanner, or open its own window. A host such
as `MiningPanel` subscribes to it and decides how to expand the layout.

```python
from app.refinery import RefineryTracker

tracker = RefineryTracker()
tracker.subscribe(lambda event: print(event.event_type,
                                      event.is_refinery_order_active))
tracker.start()                 # emits the restored state immediately
...
tracker.close()
```

- It tails `~/starcitizen/LIVE/Game.log` read-only, then falls back to
  `SC_GAME_LOG`, the normal LIVE/PTU/EPTU locations, and CrossOver/Whisky
  bottles. A missing log is normal: the watcher waits and retries.
- Jobs persist to `refinery_jobs.json` in the same per-user config directory as
  the other caches. Each job stores system, station, processing method, start
  timestamp, duration/countdown and end timestamp, so multi-day orders survive
  restarts.
- `is_refinery_order_active` is true while at least one timer is running.
  `state_changed` events carry that boolean; `state_queue` also receives the
  booleans for a host that prefers polling a `queue.Queue`. Snapshot helpers are
  `tracker.jobs`, `tracker.active_jobs`, `tracker.countdowns` and
  `tracker.state`.
- Other events are `job_started`, `job_complete`, `countdown` and
  `jobs_changed`. `countdown` is emitted once per second while work is active.
  Callbacks run on the tracker's dispatcher thread, so a Qt host should marshal
  them to the UI thread. `RefineryEvent.to_dict()` and
  `tracker.state.to_dict()` are ready for a Qt signal or a JSON bridge.
- When a timer hits zero the tracker queues an OS speech alert saying
  “Refinery order complete” from a dedicated worker thread. macOS uses `say`,
  Windows uses SAPI through PowerShell, and Linux uses `spd-say`/`espeak`; an
  optional WAV can be supplied as a fallback. Pass
  `audio=RefineryAudio(enabled=False)` to silence it.
- Log formats change. The default parser accepts broad refinery/work-order
  triggers and fields such as `station`, `location`, `system`, `method`,
  `duration`/`time_remaining`, `commodity` and `quantity`. If a patch omits the
  duration, call `tracker.add_job(...)` manually; pass custom
  `RefineryLogParser` patterns through `log_watcher_factory` if needed.

The tracker is read-only and anti-cheat-safe: no memory reads, injection, input
synthesis, or game-file writes. It is not wired to the scanner layout in this
repository yet; that is deliberately left to the host UI.

## Ore finder

`ORE FINDER` on the nav bar opens a live copy of
[scminer.rocks/data/where-to-mine](https://scminer.rocks/data/where-to-mine):

- The list is every minable ore with its price per SCU, scan signature and best
  hotspot. Filter with `ALL / SHIP / ROC / FPS`.
- Click an ore to see the ranked hotspot list: system, body type, abundance %,
  gravity, hazard and the suit or gear it needs.
- Below that: every refinery deck with its yield bonus, the recommended laser
  and gadget, and the page's thermal/cryogenic warnings.
- If the scanner has locked a rock, opening the ore finder jumps straight to
  that ore's page.

The list is one request, and each ore page is fetched the first time you open
it (about 0.5 s). The `↻` button re-syncs. If the site cannot be reached the
panel keeps working from the last snapshot and shows `OFFLINE` plus the cache
time, so it never goes blank mid-flight. The footer says how old the list is
(`SYNCED 5 MIN AGO`, or `NOT SYNCED`), and the header turns to an amber `STALE`
once the list is older than its 15-minute lifetime.

Data belongs to [SCMINER](https://scminer.rocks) and is fetched on demand for
personal use; the footer shows the patch number the data came from.

## Combat log

The **COMBAT** tab in the nav bar shows the live `Game.log` feed: victim,
attacker, weapon, soft-dead/destroyed status, and session counters. **DAMAGE**
also shows weapon-impact and hull-damage lines; **CLEAR** clears the feed
without resetting the session stats. The feed keeps the newest events first and
does not write anything to disk. It shows the victim/attacker pair exactly as
logged; it does not yet know which character name is yours, so it does not label
one side as “you”. `DOWNED` means a ship at `Soft-Dead`; FPS knockdown is not a
separate state in the current parser. The header says `LIVE` only while
`Game.log` has been written in the last 2 minutes; otherwise it says
`IDLE · last event 5 min ago` (or `IDLE` before the first line).

Under the hood, `app/combat.py` and `app/combat_log.py` stay Qt-free. The
tracker reads `Game.log` asynchronously, updates one target state per ship or
actor, and publishes structured payloads. `app/ui/combat_panel.py` is only a
renderer subscribed to `OverlayApp.combat_event`. The UEX HTTP client stays in
`app/hauling.py`, `app/planner.py` and the station snapshot; only the
marketplace search panel was removed.

```python
from app.combat import CombatTracker

tracker = CombatTracker()
tracker.subscribe(lambda event: print(event.to_dict()))
tracker.start()                 # starts the read-only log watcher
...
tracker.reset_session()         # start a fresh gameplay loop
tracker.close()
```

The host overlay wires the tracker to `OverlayApp.combat_event`, a Qt
`Signal(object)`, and the COMBAT panel renders those payloads. A host can also
poll `tracker.event_queue`, which receives `CombatEvent` objects, or read
`tracker.stats` / `tracker.state` directly. A typical HUD alert filters terminal
statuses:

```python
if event.status == "Soft-Dead":
    show_hud("Target Disabled (Soft Death) - Clear to Board")
elif event.status == "Destroyed":
    show_hud("Target Destroyed")
```

Every payload includes:

- **Timestamp** — the UTC epoch from the `Game.log` line, plus an ISO string in
  `to_dict()`;
- **Target name and type** — for example `Gladius` / `Vehicle`, or the victim
  actor name / `Actor`;
- **Operational status** — `Active`, `Soft-Dead`, or `Destroyed`;
- optional attacker, weapon, damage type, zone, destroy level and raw line.

The parser recognises the current `CVehicle::OnAdvanceDestroyLevel` line and
distinguishes `Soft-Dead` (destroy level `0 → 1`, hull disabled but intact)
from `Destroyed` (`1 → 2` or `0 → 2`, catastrophic explosion). It also parses
`CActor::Kill` player-kill lines and broad, configurable vehicle-damage and
weapon-impact patterns. A late soft-death line cannot downgrade a destroyed
target, and repeated terminal lines do not flash the HUD twice. If a patch
changes the prose, pass a `CombatLogParser` with custom patterns through
`CombatTracker(log_watcher_factory=...)`; the stable destroy-level and actor-kill
formats remain available.

Session analytics are scoped to the active gameplay loop:

- unique targets neutralised, soft-dead and fully destroyed;
- total damage events, weapon impacts, kills, player kills and deaths;
- engagement count, the last time delta between neutralisations, and the mean
  interval;
- survival uptime, current survival stretch and longest stretch;
- time since the last event and last damage.

Call `reset_session()` (or `reset_analytics()`) to clear targets, counters and
timing. `flush_stats(reset=True)` returns the completed loop's snapshot and
starts a clean session in one call. The tracker keeps no persistent combat
history by default.

Parsing and stats stay off the UI thread: the watcher runs in its own daemon
thread, and listeners run on the event-bus dispatcher. A Qt host should connect
`combat_event` with a queued connection when the receiver must run on the GUI
thread.

## Blueprint / inventory tracker (headless)

`app/blueprints.py` and `app/blueprint_log.py` add a windowless crafting and
inventory feed. The watcher tails `Game.log` read-only, the parser extracts
blueprint names, layout/class codes, item names, quantities and loot containers,
and the registry worker persists permanent history to
`unlocked_blueprints.json`. No widget or window is created.

The canonical blueprint notification is the authoritative line Star Citizen
writes for an unlock:

```text
<2026-03-26T17:15:41.684Z> [Notice] <SHUDEvent_OnNotification> Added notification "Received Blueprint: Defiance Helmet Tactical: " [23] to queue.
```

The parser ignores the matching `<UpdateNotificationItem>` echo and bare
continuation lines, so one unlock produces one event. It also recognises broad
`CraftingBlueprint` / recipe unlock forms and inventory-database or loot lines
such as `CInventory::AddItem item_name='FS-9 LMG' quantity=1` and
`Opened loot box 'Crate_123' and found item 'Coda Pistol'`. The broad patterns
are configurable through `BlueprintLogParser`.

```python
from app.blueprints import BlueprintTracker

tracker = BlueprintTracker()
tracker.subscribe(lambda event: print(event.to_dict()))
tracker.start()
...
tracker.close()
```

The host overlay wires the tracker to two Qt signals:

- `OverlayApp.blueprint_unlocked_signal` — emits exactly
  `{"item_name": str, "timestamp": str, "is_new_unlock": bool}` for a blueprint
  acquisition. `is_new_unlock` is `False` when the registry already contains the
  blueprint, so a toast can say “already known” or skip the alert.
- `OverlayApp.inventory_event_signal` — emits the full event dictionary,
  including `event_type`, `item_code`, `quantity`, `container`, `is_new` and
  `checked_off`.

For a backend-only consumer, `tracker.subscribe_blueprints(listener)` calls
`listener` with the same three-key dictionary. A host can also poll
`tracker.event_queue`, read `tracker.last_event`, inspect
`tracker.blueprints` / `tracker.items`, call `tracker.is_unlocked(name)`, or read
`tracker.stats`. Acquired blueprints and components are stored with
`checked_off: true`, so a shopping list can mark them off without another file
format. The worker loads the registry before processing events, which is how a
fresh launch distinguishes a new drop from a duplicate.

Parsing, registry lookups and JSON writes stay off the UI thread. The log watcher
and registry worker are daemon threads, and callbacks run on the
`sc-blueprint-events` dispatcher. A Qt receiver should use a queued connection
when it must run on the GUI thread. Set `SC_GAME_LOG` to override the log path,
or pass `registry_path=` / `log_watcher_factory=` for tests or alternate
installs.

## NOTES

`NOTES` is a plain notepad next to `COMBAT`, for anything worth remembering —
routes, buyers, spawn rules, prices — without leaving the game.

- Type and it saves itself: a write is queued 700 ms after the last keystroke,
  and again when the panel is hidden or the app quits.
- The status chip reads `SAVED`, `SAVING…`, or `NOT SAVED` with the reason.
- Stored as plain UTF-8 at `%APPDATA%\SC Assistant\notes.txt`, so it can be
  opened, edited or backed up with any text editor. Writes go through a
  temporary file and a rename, so a crash cannot leave a half-written note,
  and the previous version is kept as `notes.txt.bak`.
- If `notes.txt` cannot be read (another program has it locked, for example),
  the chip reads `NOT LOADED`, the footer gives the reason and the editor is
  read-only, so nothing is ever saved over the real notes. Close the other
  program, then reopen NOTES.
- The footer shows the character count and the file name.

## HAULING

`HAULING` sits directly beside `ORE FINDER` and has three tabs:

- **TRADE ROUTES** — live commodity buy → sell routes from the public UEX API
  2.0: prices, stock, distance, profit per SCU, ROI and trip profit. By default
  no specific commodity is selected: the tab opens on the most profitable routes
  across every tradable commodity.
- **CONTRACTS** — a reference board of community-collected hauling missions
  (payout, rank, contractor, pickup/drop-off locations and SCU per leg).
  There is no public live hauling-contract API, so this tab is a **snapshot**,
  not a live mission board. It is clearly labelled `SNAPSHOT` / `NOT LIVE`.
- **HAULING PLANNER** — a profit-per-minute optimizer. It uses the same cargo
  capacity as TRADE ROUTES, then ranks complete buy → sell runs by estimated
  aUEC per minute after stock, budget, quantum distance, atmosphere and loading
  time. Each row exposes the path, investment, gross profit, duration and PPM.

Set **CARGO** to the SCU capacity of the ship you are flying; trip profit,
`FITS` and stock reliability are calculated from it.

The commodity box starts on **All commodities — top routes**. It lists the 500
best routes for the current cargo setting and shows each route's commodity in
the second line. Selecting a commodity switches to that commodity's complete
route list. The first all-commodity sync checks every tradable commodity (about
205 in the current UEX snapshot) and takes roughly 20 seconds; progress is shown
in the panel and the result is cached for 15 minutes.

### Planning filters

The three filter buttons combine, and the footer shows the reduced route count
(for example `98/264 ROUTES` or `TOP 500/7,254`):

- **AUTO-LOAD** — keeps runs where both ends are a major city or orbital station
  with a freight elevator, and removes planetary outposts. UEX does not publish a
  single "instant loading" flag, so this is an approximation: it excludes the
  small outposts that require manual cargo-grid work, but you should still
  confirm the loading service at the terminal in game.
- **CITIES + STATIONS** — uses UEX terminal metadata (`id_city` or
  `id_space_station`) to hide tiny or high-gravity outposts and keep major
  landing zones and orbital stations. Useful for large ships that need room to
  manoeuvre.
- **RELIABLE STOCK** — hides runs whose reported reachable stock cannot fill the
  configured cargo capacity. Each row also shows `STOCK OK`, `ONLY n SCU` or
  `STOCK ?`, so a short supply is visible even with the filter off.

Trade routes auto-refresh every five minutes while the panel is open; the `↻`
button refreshes immediately. UEX reports community price/stock data roughly
hourly, not in real time, so stock can still change before you arrive. The
footer shows the last update time and the route count.

### HAULING PLANNER

The planner is deliberately separate from the live TRADE ROUTES list. It is a
headless engine (`app/planner.py`) plus a thin UI worker
(`app/ui/hauling_planner.py`), so network calls, cache reads and the route maths
never run on the UI thread.

For each buy → sell pair it calculates:

- **Trip size** — `min(cargo capacity, reported stock, affordable SCU)`. A
  capital cap reduces the load rather than throwing away an otherwise usable
  route.
- **Investment** — buy price × trip SCU.
- **Gross profit** — (sell price − buy price) × trip SCU.
- **Duration** — loading/unloading, quantum travel, cross-system jump, docking
  and atmospheric penalties. Manual grid loading is deliberately slower than a
  major station's auto-load/freight-elevator service.
- **PPM** — gross profit ÷ duration, in aUEC per minute.

The path column shows the ordered route, including an orbit marker when a
planetary atmosphere is involved and a jump marker when the route crosses star
systems. UEX does not publish exact 3D coordinates, so quantum time uses the
published route distance in Gm plus the system/planet/orbit anchors and fixed
jump, atmospheric and loading constants. The defaults are a 0.35 Gm/s quantum
speed, auto-load base time, manual-load time per SCU, and city atmosphere
penalties (Area 18, Lorville, New Babbage, Orison and Levski).

Planner filters:

- **AUTO-LOAD** — only routes where both ends report auto-load/freight-elevator
  service.
- **LOW GRAVITY** — removes high-gravity cities and planet-side outposts,
  leaving orbital stations and low-gravity moon locations.
- **CAPITAL** — maximum aUEC to invest in one run. Leave it blank for no limit.
- **RANK BY PPM / PROFIT / TIME / INVEST** — re-ranks the routes by the selected metric; the planner recomputes on the worker thread.

The result list shows the 500 highest-ranked matches, with `PPM`, `PROFIT`,
`INVEST`, `SCU`, `MIN`, the path, and `AUTO`/`MANUAL` plus `LOW-G`/`ATMO`
badges. Hover a row for the loading, QT, jump and atmosphere breakdown.

Data is cached in `routes_cache.json` with a 15-minute refresh interval. The
cache stores commodity prices, raw route stock/demand, terminal navigation
anchors (system, planet, moon, orbit) and the timing model. When the file is
missing, the planner can seed itself from the existing `hauling_top_routes.json`
cache so the first open is instant; press **REFRESH** to force a full UEX sync
and rebuild the cache. If UEX is unreachable, the last good cache is used and
the header/footer say `CACHED` or `OFFLINE`.

### Workflow engine

`app/workflow.py` is a headless, thread-safe state machine that turns a chosen
Commodity-tab `Route` or a planner `PlannerRoute` into one active hauling run.
It creates no windows and imports no Qt classes; the hosting panel subscribes to
events and switches its own view.

The bridge stores an immutable `ActiveRouteManifest` with the session ID and
timestamp, commodity, total SCU, purchase price, origin (station/city and
auto-load), destination (station/city, gravity and demand price), base
investment, gross projected profit, target PPM, planned duration and the live
cargo-loss state. Commodity-tab routes without a planner PPM get an estimate
from the same timing constants used by the HAULING PLANNER.

```text
BROWSING ──initialize_hauling_job(route)──▶ LOCKED_LOADED
                                              │
                              pilot seat / begin_transit()
                                              ▼
                                          EN_ROUTE
                                           │    │
                              complete_hauling_job  abort_hauling_job
                                           ▼    ▼
                                       COMPLETED / ABORTED
```

`initialize_hauling_job()` maps the route, deducts the base investment from the
unlocked wallet, writes `active_run.json`, starts the read-only `Game.log`
tailer and emits `target_state="HAULING"` with the manifest. A pilot-seat enter
event advances `LOCKED_LOADED → EN_ROUTE`; entering the destination emits
`destination_reached` (automatic completion is opt-in).
`adjust_active_manifest(cargo_lost_scu)` subtracts lost cargo, recalculates
gross profit and live PPM, and rewrites the active cache. Completion sells the
remaining manifest SCU at the destination price (or an explicit `sale_price`);
abort releases the reservation and accepts an optional `salvage_proceeds`. Both
clear the active cache and settle `workflow_wallet.json`.

Events are delivered asynchronously through a queue-backed listener thread, so
a listener must marshal to the GUI thread before touching widgets. Keep the
engine for the process lifetime; call `close()` on application shutdown.

```python
from app.workflow import HaulingWorkflowEngine

engine = HaulingWorkflowEngine(starting_capital=2_000_000)
engine.subscribe(on_workflow_event)          # event.manifest_data, target_state

manifest = engine.initialize_hauling_job(route, cargo_capacity=32)
# ... pilot seat detected from Game.log ...
engine.adjust_active_manifest(cargo_lost_scu=4)
engine.complete_hauling_job(sale_price=manifest.destination.demand_price)
engine.close()
```

If `starting_capital` is omitted, the ledger starts with unknown capital and
will not reject a run; call `set_trading_capital()` before locking a load to
enforce the budget. State is stored under the normal per-user config directory
(`~/Library/Application Support/SC Assistant/` on macOS,
`%APPDATA%\SC Assistant\` on Windows): `active_run.json` is the resume cache and
`workflow_wallet.json` holds cash, reservations, realized profit and run counts.

The log tailer looks at `SC_GAME_LOG` first, then common LIVE/PTU/EPTU install
paths (including CrossOver and Whisky bottles on macOS). A missing log never
stops the engine; the monitor waits and retries. It reads the file only, starts
at the current end of file, and tolerates rotation/truncation. Default parsing
covers pilot-seat enter/exit notifications and the common `location`/`arriving
at` forms; pass a custom `log_monitor_factory` if a patch changes the log text.

### Data and safety

Trade routes and terminal metadata come from `api.uexcorp.uk/2.0`. The contract
snapshot is generated from
[FSCSOFT-Official/SCHaulingPlanner](https://github.com/FSCSOFT-Official/SCHaulingPlanner)
(MIT) and bundled in `app/data/hauling_missions.json`, with a background refresh
from GitHub when available. Routes — including the combined top-routes cache —
cache for 15 minutes, commodities for 12 hours, terminals for 7 days and
contracts for 24 hours; the last good data is kept when a source is unreachable.
The panel says how old the data on screen is (`UPDATED 5 MIN AGO`) and shows
`LIVE` while it is within its cache lifetime; past it (for example while UEX
cannot be reached) the status turns to an amber `STALE`.

HAULING only makes read-only HTTP requests and reads local JSON. The workflow,
combat and blueprint/inventory trackers additionally tail Star Citizen's own
`Game.log` read-only to detect pilot-seat, location, combat, blueprint and item
events. They do **not** read game memory, inject code, synthesise input, or
modify the game in any way.

## UEX

`UEX` is a search box for the player marketplace at
<https://uexcorp.space/marketplace/>.

- Type an item or commodity (`p6`, `quantanium`) and press **Enter** or
  **OPEN**. The marketplace opens in your browser with that search applied — the
  full board, weapons and commodities, with quality and every listing the site
  shows.
- With the box empty, **OPEN** takes you to the marketplace home page.
- The footer shows the exact URL that was opened.

Why a launcher rather than a list: the marketplace board is rendered
server-side behind Cloudflare and has no public JSON feed. The public API only
serves a capped page of commodity ads (500 rows), which is why an in-app list
found one hephaestanite ad where the website had dozens. Linking to the real
page is smaller, always current, and cannot break when UEX changes their
backend.

Trade routes, prices and stock still come from the API — see *HAULING* above.

## INVENTORY

`INVENTORY` is a manual stash notebook, not a live game-inventory reader. Use it
to remember loot or supplies you left at another station so you can find them
again later.

Add a note with:

- **Station** — required; start typing and the dropdown searches the bundled
  UEX station snapshot. A few letters are enough (for example `sera` finds
  `Seraphim Station`). You can still type a location that is not in the list.
- **Item or loot** — required; what is there.
- **Qty** — optional free text, for example `2`, `12 SCU` or `a crate`.
- **Note** — optional; container, locker, hangar bay, etc.

Click any note to edit it. Click the `✕` on a row once to arm deletion and again
to confirm. Search filters across item, location and note. **RECENT** sorts newest
first; **LOCATION** groups notes by where they are stored.

Everything is stored locally in `%APPDATA%\SC Assistant\inventory.json` (or
`~/Library/Application Support/SC Assistant/inventory.json` on macOS). Nothing is
sent anywhere. If the file cannot be read, the panel shows `NOT LOADED` with
the reason and does not allow adding, editing or deleting notes until it can,
so the file on disk is never replaced. The panel can take keyboard focus, so F3/F4 still work as
application shortcuts while you type.

## Settings window

`⚙` on the nav bar opens the settings window. Its controls are in six groups,
top to bottom. Each group has a heading you click to open or close it: `▸` when
closed, `▾` when open. Any number of groups can be open at once, and the window
resizes to fit. A closed heading shows a short grey summary on its right:

| Group | Holds | Summary while closed |
|---|---|---|
| **SCANNER** | *Signature capture region*, *Scanning* | the monitor · `no box` or `box set` |
| **SCAN DATA** | *Signature data*, *Unmatched readings* | `<N> ores · <M> unmatched` (only `<M> unmatched` until the signature table has loaded) |
| **HOTKEYS** | *Hotkeys* | SHOW BAR and HIDE ALL, e.g. `SHOW BAR F3 · HIDE ALL F4` |
| **LOOK & SOUND** | *Appearance*, *Voice* | e.g. `UI 100% · voice on` |
| **UPDATE & RESET** | *Update*, *Reset* | `v<x> installed`, or `v<x> available` after CHECK found a newer one |
| **SUPPORT** | *Support* | nothing |

Where a group holds two of the old sections, their names stay as small
sub-headings inside it. The open groups are remembered (`settings_open` in
`config.json`); the first time only SCANNER is open. While no scan box has been
drawn, SCANNER stays open and its heading cannot close it, so DRAW REGION is
always in view; once the box is drawn SCANNER stays open until you close it.
Closing HOTKEYS cancels a key change that was waiting for a key press.

**SCANNER**

*Signature capture region*

- **MONITOR** picks the monitor the game runs on
  (each entry shows the monitor's real resolution and Windows scaling, e.g.
  `LG ULTRAGEAR+ · 5120×2160 · 150%`); **DRAW REGION** re-calibrates on
  that monitor. An amber note appears when the box was moved because the
  monitor changed, and it says what happened to tracking (see *Calibrating
  the scanner*).

*Scanning*

- **READS / S** — how many times a second the box is read, 1–8 (default 4).
  Applies immediately and is saved as `poll_ms`. Fewer reads use less CPU; more
  reads lock onto a new rock sooner.
- **TRACKING** — how far the scanner looks for the plate's pin around the box
  as the HUD sways, `OFF` or ±50 to ±800 px (default ±400 across, ±300 up and
  down, for a 2160-px-high screen; scaled for others). The slider moves in
  50 px steps; the label follows a drag, and the new range is applied and
  saved as `tracking_range` once, when the slider is released. Needs a pin
  saved by **DRAW REGION** or learned from a scan (see *Calibrating the
  scanner*).
- **PAUSE / RESUME** — stop OCR without closing anything.
- **SHOW PREVIEW** — show the raw pixels being read; useful for checking the box.
- **SHOW BOX** — draw a thin outline on screen around the box being read
  (with tracking on, around the pin and the digits it has found, with a
  `TRACKING ✓` / `SEARCHING…` / `FIXED BOX` label). It sits just outside the
  box, lets clicks through, and is always hidden from
  screen capture, so neither the scanner nor screenshots ever see it. F4 hides
  it with everything else. Off by default (`show_region_outline`): like any
  window over the game it can cost frames, so use it to check the box, then
  turn it off.

**SCAN DATA**

*Signature data*

- Where the signature table came from, for example
  `Signatures: scmdb 4.10.2 live · 26 ores`, or `bundled 4.10.2` with the
  reason scmdb was not used; **RELOAD** re-reads it without restarting (see
  *Signature data*).

*Unmatched readings*

- How many readings matched nothing (`None saved`
  or `N saved`) and the newest three (number and time). **OPEN FOLDER** opens
  `%APPDATA%\SC Assistant\unmatched\`; **CLEAR** deletes the list and its
  pictures after a second click (the first changes it to `CLEAR?` for about
  3 seconds). See *Unmatched readings* under *Reading the scanner*.

**HOTKEYS**

- One row per key: **SHOW BAR** (default F3), **HIDE ALL**
  (default F4), then one per tool (MINING, ORE FINDER, HAULING, UEX,
  INVENTORY, COMBAT, NOTES; none by default). Click a key button, then press
  the new key; Esc sets no key. A key already used by another row is refused
  with a note. The keys apply at once, without a restart, and are saved as
  `hotkey_toggle_nav`, `hotkey_panic` and `hotkey_tools`.

**LOOK & SOUND**

*Appearance*

- UI scale (75–150% in 5% steps) and opacity slider
  (30–100%) for the content panels (mining, ore finder, HAULING, UEX, INVENTORY,
  COMBAT and NOTES); the nav bar and settings window stay fully visible while you
  adjust opacity. The **VISIBLE/HIDDEN** button beside *Shown in screenshots and
  streams* controls whether the windows appear in screenshots, OBS and screen
  shares (stored as `capture_exclude`).
  The scale is applied by the overlay itself (`app/ui/theme.py`) rather than by
  Qt's `QT_SCALE_FACTOR`, because that variable only changes widget geometry on
  Windows/Linux — on macOS it was ignored, which is why the slider used to do
  nothing there. Widgets are built once, so a new scale needs a fresh process:
  the hint under the slider turns amber and the **RESTART** button relaunches the
  overlay in place (positions and settings are saved first). At the default 100%
  nothing is scaled and the layout is pixel-identical to earlier builds.

*Voice*

- **VOICE** — turn on or off spoken announcements and set their volume (see *Voice* above).

**UPDATE & RESET**

*Update*

- The installed build and a **CHECK**
  button. When something newer exists the button becomes **UPDATE**, and
  "What's new in vX" from that release's notes is shown under it (plain text
  only). What UPDATE does depends on the install:
  - **Installed EXE** (from the Setup): CHECK reads the latest GitHub release
    of this fork, `swill008/sc-assistant`. UPDATE downloads that
    release's Setup, checks its size and its SHA-256 digest against GitHub's,
    and names the version it actually downloaded (it can be newer than the one
    CHECK saw). SC Assistant then closes, Setup installs silently and
    starts the new version. The hand-off waits for the old copy to exit with
    no time limit; if Setup stops without installing (exit code 1 or 2), the
    old version is started again.
  - **Standalone EXE** (unzipped): UPDATE opens the Releases page; download
    the new zip.
  - **Source install** (`install.bat`): CHECK reads `app/version.py` from this
    fork; UPDATE downloads the `main` branch archive and copies `app/`,
    `tools/`, the launchers and the requirements over this folder, then
    restarts the overlay. `opencode.jsonc` is deliberately left alone.

  Settings, notes and logs live in `%APPDATA%\SC Assistant` and are never
  touched. Quitting during a download cancels it.

*Reset*

- The red **RESET SETTINGS** button puts the
  settings back to their defaults. Click it twice, like QUIT: the first click
  changes it to `CLICK AGAIN TO RESET` for about 3 seconds. Then:
  1. the whole `%APPDATA%\SC Assistant` folder is copied to a backup folder
     next to it, `SC Assistant backup <YYYY-MM-DD HHMMSS>`;
  2. removed: `config.json` (the box, pin, monitor, READS / S, TRACKING,
     SHOW BOX, hotkeys, panel positions and pinned windows), the saved pin
     picture `anchor.png`, the downloaded caches (`signatures_scmdb.json`,
     `where_to_mine.json`, `routes_cache.json`, `hauling_*.json`), their
     `.bak` copies, and the `unmatched` folder;
  3. kept: `notes.txt`, `inventory.json`, the blueprint registry
     (`unlocked_blueprints.json`), the refinery timers (`refinery_jobs.json`),
     the hauling run and wallet (`active_run.json`, `workflow_wallet.json`),
     `error.log`, their `.bak` files, and any file the app does not know;
  4. the app restarts with default settings; draw the scan box again.

  If the files cannot be removed (for example one is open in another
  program), nothing is removed and the note says `Reset failed, nothing was
  removed: …`. To undo a reset, quit the app and copy the files back from the
  backup folder.

**SUPPORT**

- "Like my overlay? Buy me a coffee (or a ship)!" with a BTC
  address and copy button.

The settings window has a push-pin too, like every panel.

Advanced scan tuning lives in `config.json`: `poll_ms` controls the capture
cadence (default `250`, i.e. 4 reads a second; **READS / S** sets it, and
existing installs on the old `125` default move to `250` once),
`fast_single_read` enables the high-confidence
single-read lock, and `fast_confidence` sets its confidence threshold (default
`0.97`). Set `fast_single_read` to `false` to always require two reads.
`ocr_threads` (default `1`) is how many CPU threads the OCR model may use; see
*Game performance* below before raising it.

Settings are saved to `%APPDATA%\SC Assistant\config.json`, next to the ore-location
cache (`where_to_mine.json`), inventory notes (`inventory.json`), the planner
route cache (`routes_cache.json`) and the workflow caches (`active_run.json`,
`workflow_wallet.json`), the scmdb signature cache (`signatures_scmdb.json`)
and the saved pin picture (`anchor.png`). Panel positions (mining, ore finder,
HAULING, UEX, INVENTORY, COMBAT, NOTES), pinned panels (`pinned_windows`) and
the nav bar's visibility are also stored in `config.json` when the app quits
normally, so they reopen where you left them.

**Your own files are never replaced by a failed read.** `notes.txt`,
`inventory.json`, the blueprint registry (`unlocked_blueprints.json`) and the
ore-finder cache all go through one shared store (`app/safe_store.py`):

- A file that exists but cannot be read (locked by an editor, a backup tool or
  a virus scanner, no permission, or broken JSON) is reported as not loaded,
  never treated as empty. NOTES and INVENTORY show `NOT LOADED` and do not
  save; the blueprint registry is not saved for that session.
- Broken JSON is copied once to `<name>.bad-<date-time>` so it can be
  recovered by hand; the original stays where it is.
- Every save writes a temporary file and renames it over the old one, and the
  previous file is kept as `<name>.bak`.
- A Windows file lock is retried 5 times, 0.1 s apart, before a read or save
  gives up.
- Files are read as UTF-8 (with or without a BOM), and a file saved in
  Windows-1252 by another editor still opens.
- The ore-finder cache is only a copy of the website, so a bad file or a bad
  entry is skipped and the next sync rewrites it.

> If the venv was built from the Microsoft Store build of Python, Windows
> redirects those writes into the app package container, so the files live under
> `%LOCALAPPDATA%\Packages\PythonSoftwareFoundation.Python.3.13_*\LocalCache\Roaming\SC Assistant\`.
> A python.org install uses the plain `%APPDATA%` path.

## Game performance

The scanner shares the CPU and the display with Star Citizen, so it is built to
stay out of the game's way.

**OCR on one low-priority thread.** `rapidocr-onnxruntime` creates its ONNX
Runtime sessions with the library defaults: a worker pool as wide as the CPU,
whose threads spin while they wait. Every scan (8 a second) then burst across
most cores at once. `app/ocr.py` now builds the sessions with
`ocr_threads` threads (default 1), no spinning and sequential execution, and the
scanner thread runs at below-normal priority, so a scan waits for the game
rather than the other way round. Measured on a Ryzen 7 9800X3D (8 cores, SMT
off) with the 42,000 signature from a 5K2K screenshot:

| OCR setup | CPU per read | Cores busy during a read | Time per read |
| --- | --- | --- | --- |
| Library defaults (before) | 37.7 ms | 6.3 | 6 ms |
| `ocr_threads: 1` (default) | 6.4 ms | 0.4 | 17 ms |
| `ocr_threads: 2` | 8.6 ms | 0.6 | 15 ms |

17 ms is well inside the 250 ms default scan interval (and the 125 ms one at
8 reads a second). In game (PresentMon frame
captures, 150 s each), the old build gave about 10× more frame hitches than
with the overlay closed (33–53 versus 3–6, worst 1% of frames 34–41 ms versus
18–19 ms); limiting the overlay to two cores at low priority brought it back to
the overlay-closed numbers. Only raise `ocr_threads` on a CPU with spare cores.

**Overlay windows over the game.** Any always-on-top window that covers a
borderless game (this overlay's nav bar and panels, or another app's) makes
Windows composite every game frame through the desktop window manager instead
of letting the game flip straight to the display. Measured with the scanner on
one core: hiding every overlay window raised the game from 60.6 to 69.7 FPS
and the worst frame from 78 ms to 18 ms. Close panels you are not using, or hide
the overlay with **F3**/**F4** when you do not need it. **SHOW BOX** is such a
window too, which is why it is off by default.

**Reads per second.** Each read costs about 6 ms of CPU on one core, so the
default 4 a second is about 2.5% of one core; 8 a second doubles that.

**Tracking.** Finding the pin costs about 1.3 ms per read (95% under 4 ms) on
the default search area, and saves the OCR's 6 ms whenever no plate is on
screen, so with tracking on the scanner usually uses less CPU than without.

To check your own system, Intel's free
[PresentMon](https://github.com/GameTechDev/PresentMon) records every frame:
`PresentMon --process_name StarCitizen.exe --timed 150 --output_file frames.csv`
(run as administrator). The `PresentMode` column says `Hardware: Independent
Flip` when nothing is composited over the game and `Composed: Flip` when
something is.

## Signature data

The signature table comes from [scmdb.net](https://scmdb.net)'s game data by
default, with the bundled file as the fallback (`app/sigsource.py`,
`app/mining.py`):

- In a background thread, at most once a day, the app reads
  `https://scmdb.net/data/versions.json`, picks the newest build for the chosen
  channel and downloads its `mining_data-<version>.json`. The converted table
  is cached as `signatures_scmdb.json` in `%APPDATA%\SC Assistant` and
  used from then on; a failed download keeps the cache.
- Until a cache exists, or when it cannot be used, the bundled
  `app/data/signatures.json` is used, and Settings → *Signature data* says why
  (`bundled 4.10.2 (scmdb unavailable: …)`).
- `signature_channel` in `config.json` is `live` (default) or `ptu` for the
  test server. `signature_source: "bundled"` never downloads and always uses
  the bundled file.
- scmdb gives the ores, their base signatures and the ground lists; the short
  names, values, rarity, secondary ores and salvage still come from the
  bundled file, matched by name. On 2026-11-01
  the bundled ship bases and both ground lists were equal to scmdb's
  `4.10.2-live.12913470` (and `4.10.3-ptu.13055118`).

Each ship-ore entry is a base signature:

```json
{ "name": "Borase", "rarity": 4, "base": 3570,
  "secondary": "Gold / Bexalite 5-10%" }
```

The loader expands each base into `base × count` for the 1-10 rock cluster
sizes shown by the SCMINER scanner, so adding an ore is a one-line edit. ROC
(4,000, 1-25 deposits), hand-mining (FPS, 3,000, 1-21), salvage debris (2,000,
1-50) and harvestables (2,000, 1-10) use their own base values and limits
(see *Scan limits*), and the two ground kinds each have their own mineral
list: `ground.fps_minerals` (8) and `ground.roc_minerals` (22).

A number can match more than one kind; every exact match is kept. Ship ore
always comes first. Up to 30,000, the most a scrap field reaches in the game
data (15 pieces), salvage comes next (debris, harvestables, then ROC and hand
mining), so 8,000 in space still reads DEBRIS ×4. Above 30,000 a ground
cluster is far more likely, so ROC and hand mining come first: 76,000 reads
ROC ×19, then DEBRIS ×38. The near (`~`) guesses follow. The panel shows the
first and, when there is one, a second exact match of another kind on its own
line. The reader accepts 2,000 to 100,000 (`min_value` / `max_value`).

## Anti-cheat

Star Citizen runs Easy Anti-Cheat. This overlay only:

- captures pixels from the desktop with `mss`,
- runs a local OCR model on the cropped image,
- draws its own always-on-top, click-through-ish windows,
- reads and writes its own local JSON notes for the inventory panel,
- reads and writes its own planner and workflow caches,
- tails Star Citizen's `Game.log` read-only for workflow, refinery, combat and
  blueprint/inventory events,
- reads and writes its own local refinery timer registry,
- reads and writes its own local `unlocked_blueprints.json` unlock registry,
- makes read-only UEX HTTP requests for hauling, planner and station data,
- downloads signature data from scmdb.net (read-only, at most once a day).

It never opens a handle to the game, reads its memory, injects a DLL, or
synthesizes input into the game. That keeps it on the safe side of EAC, but any
third-party overlay is still your own risk to take.

## Privacy and network access

The overlay has no server component and opens no listening port, so nothing can
connect to it. It does not hook, inject into or read the memory of the game
process: it tails `Game.log` as text and OCRs a screen region you calibrate,
entirely on your machine.

Outbound traffic is GET requests only:

| Destination | Why |
| --- | --- |
| `api.uexcorp.uk` | trade routes and the UEX marketplace tab |
| `scminer.rocks` | ore locations for ORE FINDER |
| `scmdb.net` | signature data (`versions.json` and `mining_data-<version>.json`), at most once a day; never with `signature_source: "bundled"` |
| `raw.githubusercontent.com` | hauling mission snapshot, update check for a source install (`swill008/sc-assistant`) |
| `api.github.com` | latest release of `swill008/sc-assistant` and its release notes, only when you press CHECK |
| `github.com` | the release's Setup download, only when you press UPDATE in the installed EXE |
| `codeload.github.com` | the update archive from `swill008/sc-assistant`, only when you press UPDATE in a source install |

There is no telemetry, no analytics and no account. Screenshots, notes and
inventory data are never uploaded; everything the app stores lives in
`%APPDATA%\SC Assistant`.

### Updates are manual

Nothing installs itself in the background. `⚙` → **CHECK** only asks GitHub
for the newest version (the latest release for the installed EXE,
`app/version.py` on `main` for a source install), compares it with this copy
and, when the newer version has a release, shows its "What's new" text. Pressing **UPDATE** is what
downloads anything: the release's Setup for the installed EXE, checked against
GitHub's SHA-256 digest before it is run, or the `main` archive for a source
install, copied over this folder before the overlay restarts. If you never
press it, the build stays exactly as installed.

The "What's new" text comes from `release-notes/<version>.md`, which every
release must have (see `release-notes/README.md`); `tools/release_body.py`
turns it into the GitHub release text.

Updates come from **this fork, `swill008/sc-assistant`** (`REPO` in
`app/version.py`; before 1.0.0 the repository was `swill008/citizen-assistant`,
and GitHub redirects the old address). Until v1.2.16 they came from the
original `fishtaco7/citizen-assistant`, so pressing UPDATE in this fork would have
replaced its fixes with the upstream code. The code that reaches users is
therefore whatever is committed to `main` in this fork; only its owner can push
to it.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| Nothing ever reads | Re-calibrate; the box must contain only the digits. Check the preview. |
| Nothing reads on a 5K / high-DPI screen next to monitors with other scaling | Calibrated with a build before the mixed-scale fix: the box was stored too small. Press **DRAW REGION** again; the label shows the size in physical pixels while you drag. |
| The game stutters while the overlay runs | Check `ocr_threads` is `1` in `config.json`, and **SHOW PREVIEW** and **SHOW BOX** are off; try fewer **READS / S**. See *Game performance*. |
| Reads only now and then while flying | The HUD sways away from the box. If the scanner chip says `FIXED BOX`, press **DRAW REGION** with the scan readout on screen so the pin is saved (the 3-second result should say `PIN FOUND — TRACKING ON`), and check **TRACKING** is not `OFF`. A larger range follows bigger sways. |
| Chip stays on `SEARCHING` | The pin is not in the search area: the plate is off screen, or the HUD sways further than the **TRACKING** range. Turn on **SHOW BOX** to see where it last found the plate. |
| Amber note "Pin search failed (…)" or "Could not load the saved pin (…)" | The note names the error. Press **DRAW REGION** again with the readout showing; until then the box reads as a fixed box and learns the pin from the next exact signature. |
| Amber note "No pin icon found left of the box" | The readout was not on screen (or the box was drawn somewhere else) when you pressed DRAW REGION. Open the scan HUD and press **DRAW REGION** again around the digits. |
| Scanner stopped reading after changing resolution or monitor | Look for the amber note under *Signature capture region*: the box was moved to match. Turn on **SHOW BOX** to see where it is now; press **DRAW REGION** if the HUD is elsewhere. |
| Not sure where the scanner is reading | Turn on **SHOW BOX**: the outline is drawn around the exact box. It is hidden from capture, so it cannot affect the reading. |
| Reads the wrong number | Box too large or too small, or the HUD is scaled differently — re-calibrate. |
| Ore finder list is empty | No internet, or scminer.rocks is down. Press `↻`; the cache is used when available. |
| Ore finder shows `OFFLINE` | Same as above — the data on screen is the last successful sync. |
| Combat tracker shows no events | Confirm `Game.log` is being written, or set `SC_GAME_LOG` to its path. Combat log formats are patch-dependent; update the parser patterns if a patch changes them. |
| NOTES or INVENTORY says `NOT LOADED` | The file exists but could not be read; the reason is shown. Nothing is saved over it. Close the program that has it open (an editor, a sync or backup tool), then reopen the panel. A broken JSON file is kept as `<name>.bad-<date-time>`, and the last good save as `<name>.bak`, both in `%APPDATA%\SC Assistant`. |
| A hotkey does nothing | Check `⚙` → *Hotkeys*: the row may have no key (`—`). Click it and press the key you want. |
| Settings shows `bundled` signatures with "scmdb unavailable" | scmdb.net could not be reached or its data could not be read; the bundled table is used and the next try is at the next start. |
| NOTES says `NOT SAVED` | The footer shows the reason (normally a permissions problem on `%APPDATA%`). The text is still in the editor — copy it out before closing. A hard crash can lose the last 700 ms of typing, which is the autosave delay. |
| Blueprint tracker misses an unlock | Confirm the log contains `<SHUDEvent_OnNotification> Added notification "Received Blueprint: ...`; set `SC_GAME_LOG` to the right `Game.log`. If a patch changes the wording, pass custom `BlueprintLogParser` patterns. Delete `unlocked_blueprints.json` only if you want to reset new-vs-duplicate detection. |
| Bar/scanner hidden behind a browser | It re-asserts topmost every 2 s; if it still loses, run the game borderless, not exclusive fullscreen. |
| F3/F4 do nothing while the game is focused | Fixed in Citizen Assistant v1.2.1 by polling `GetAsyncKeyState` alongside `RegisterHotKey`, because exclusive fullscreen stops `WM_HOTKEY` reaching a background thread. If it still fails, run the game borderless. |
| Bar appears twice | Two copies are running. Kill the extra `python`/`pythonw` process. |
| Start menu opens an old version | Run `install.bat` from the new folder — it repoints the shortcuts and deletes stale ones. Then compare the build stamp in `⚙`. |
| `⚙` shows no build stamp or no screenshots button | You are running a copy from before those features. Quit it from the tray, then start `run.bat` inside the folder you downloaded. |
| COMBAT does nothing and no panel appears | Usually an older build without the on-screen clamp. Check the build stamp before changing anything else. |
| UEX opens the wrong page | The box should contain only the search term, then press **OPEN**. The footer shows the exact URL that was opened. |
| Scanner shows `UNKNOWN` | The number is not in the table, or OCR dropped a digit. Check the raw value shown. |
| Yellow border and `MATCHED SIGNATURE —` | The number was read but matches nothing in the table. It is saved under `⚙` → *Unmatched readings*; open the folder, check the picture, and report it if the number is right (see *Unmatched readings*). |
| Red border | The scan plate is on screen but its number has not been readable for about a second: something covers the digits, or the box is off. Check with **SHOW PREVIEW**, then **DRAW REGION** again if needed. A number over 100,000 also shows red. |
| Settings are in a bad state, or you want a clean start | `⚙` → **RESET SETTINGS** (click twice). Notes, inventory and blueprints are kept, the old settings are copied to `SC Assistant backup <date time>` next to `%APPDATA%\SC Assistant`, and the app restarts. Draw the scan box again afterwards. |
| Nothing appears in screenshots | Open `⚙` and set the screenshots button to **VISIBLE**. If it already says VISIBLE, your build predates the toggle: run with `--capture-visible`. |
| Scanner stops reading after making screenshots visible | A panel now overlaps the calibrated scan box, so the scanner captures the overlay instead of the HUD. Move that panel away from the box, or set the screenshots button back to **HIDDEN** while mining. |
| UI scale slider seems to do nothing | It needs a restart: press **RESTART** next to the slider (or quit and start again). The hint turns amber while the chosen scale is not active yet. |
| `run.bat` says Python was not found | Install Python 3.11+ (64-bit) and tick “Add python.exe to PATH”, or run `setup.bat` once to create `C:\scov`. |
| A black console flashes when a refinery order completes | Fixed: the speech/WAV helpers start PowerShell with `CREATE_NO_WINDOW`. If you see it, you are running an older copy. |
| Scanner stays on `READING` and never locks | OCR returned no text: confirm the crop in **SHOW PREVIEW** contains only the digits, then re-calibrate. `run-debug.bat` prints the scan error; if it reports a missing module, reinstall the OCR deps with `pip install -r requirements.txt`. |

## Development

```bat
C:\scov\Scripts\python.exe -m tools.selftest     REM OCR + lookup regression checks
C:\scov\Scripts\python.exe -m tools.scan_selftest REM OCR threads, picker, rescale, settings, outline, QUIT, update source (needs a desktop)
C:\scov\Scripts\python.exe -m tools.scan_e2e_selftest REM real screen: 5K2K signature -> picker -> capture -> OCR, outline, live app (secondary monitor)
C:\scov\Scripts\python.exe -m tools.scan_e2e_selftest --primary REM the same on the main/game monitor (close the game first: a real plate on screen fails the "plate gone" step)
C:\scov\Scripts\python.exe -m tools.tracking_selftest REM pin tracking on 25 hand-labelled frames of a real flight (tools\fixtures\hud_track), speed limit
C:\scov\Scripts\python.exe -m tools.settings_persist_selftest REM READS / S, TRACKING, SHOW BOX, MONITOR and the pin survive QUIT and a restart
C:\scov\Scripts\python.exe -m tools.overlay_selftest REM SHOW BOX marks, scanner chip and pin, DRAW REGION conveniences, the ⚙ pulse (needs a desktop; invisible, secondary monitor)
C:\scov\Scripts\python.exe -m tools.datasafety_selftest REM locked / Windows-1252 / broken files never overwritten, .bak, lock retry (--old: same checks on HEAD)
C:\scov\Scripts\python.exe -m tools.signature_selftest REM scmdb conversion, ground lists, cache and fallback (--live: also a real read-only fetch)
C:\scov\Scripts\python.exe -m tools.hotkeys_selftest REM rebinding hotkeys while running, Settings -> HOTKEYS (fake user32, no real hotkey)
C:\scov\Scripts\python.exe -m tools.dataage_selftest REM data age and window pins on HAULING, ORE FINDER, COMBAT, UEX (offline)
C:\scov\Scripts\python.exe -m tools.update_selftest REM UPDATE: release lookup, sha256 check, What's new, installer hand-off, TRACKING slider (one live read-only request)
C:\scov\Scripts\python.exe tools\release_notes_selftest.py REM release_body.py and the workflows (set RELEASE_CHECK=1 to also require release-notes\<version>.md)
C:\scov\Scripts\python.exe -m tools.workflow_selftest REM workflow + Game.log checks
C:\scov\Scripts\python.exe -m tools.refinery_selftest REM refinery parser + timers
C:\scov\Scripts\python.exe -m tools.combat_selftest REM combat parser + tracker + queue
C:\scov\Scripts\python.exe -m tools.blueprint_selftest REM blueprint parser + registry + queue
C:\scov\Scripts\python.exe -m tools.preview      REM render the windows to tools\preview_out
C:\scov\Scripts\python.exe -m tools.preview --scale=1.25   REM same, at a UI scale
C:\scov\Scripts\python.exe -m app --demo         REM fake 7,200 signature, no game needed
C:\scov\Scripts\python.exe -m app --demo --open hauling      REM start with a tool open
C:\scov\Scripts\python.exe -m app --demo --open inventory   REM stash notes panel
C:\scov\Scripts\python.exe -m app --demo --open orefinder  REM (mining / orefinder / hauling / inventory / settings)
C:\scov\Scripts\python.exe -m tools.signage 10710 REM draw a signature on screen for live tests
```

The self-tests print non-ASCII text (`✓`, `·`, `→`, `—`). When their output is
redirected to a file or a pipe, Windows uses the console code page and Python
can stop with a `UnicodeEncodeError`, so set `PYTHONIOENCODING=utf-8` first
(`set PYTHONIOENCODING=utf-8` in `cmd`, `$env:PYTHONIOENCODING = "utf-8"` in
PowerShell). The overlay, data-safety, signature, hotkeys, data-age and
release-notes tests print PASS/FAIL lines, and their exit code is the number
of failures.

`--capture-visible` disables capture exclusion so the overlay shows up in
screenshots and screen shares. If your venv is `.venv` instead of `C:\scov`,
substitute `.venv\Scripts\python.exe` in the commands above.

On macOS use `./run.command --demo`, `./run.command --demo --open hauling`,
`.venv/bin/python -m tools.selftest`,
`.venv/bin/python -m tools.workflow_selftest`,
`.venv/bin/python -m tools.refinery_selftest`,
`.venv/bin/python -m tools.combat_selftest` and
`.venv/bin/python -m tools.blueprint_selftest`; there is no `pythonw`, so the
console stays attached.

## License

MIT — see [`LICENSE`](LICENSE). Use it, fork it, ship it; there is no warranty.

The overlay itself is original work. Data and assets keep their own terms: the
bundled hauling mission snapshot comes from
[SCHaulingPlanner](https://github.com/FSCSOFT-Official/SCHaulingPlanner) (MIT),
market, ore and station data belong to
[UEX Corp](https://uexcorp.space) and [SCMiner](https://scminer.rocks),
and mining signature data comes from [scmdb.net](https://scmdb.net).
Star Citizen is a trademark of Cloud Imperium Games; this project is
unaffiliated with CIG.

