# Code review — 2026-11-01 (branch feature/hud-tracking vs main, plus whole app)

Read-only review by three reviewers (R1 core logic, R2 UI widgets, R3 rest of
the app), the critical claims re-checked by the lead against the code. Qt 6 /
PySide6 **Widgets** (no QML in this app). Nothing was changed by the review.

## Verified critical / high-value findings

| # | Finding | Where | Verified |
|---|---|---|---|
| 1 | Notes erased: failed read → empty editor → flush on hide/quit writes "" over notes.txt | notes.py:20-24, ui/notes_panel.py:129-134, main.py:448 | yes |
| 2 | Non-UTF-8 notes.txt crashes start-up (UnicodeDecodeError not caught) | notes.py:22-23 | yes |
| 3 | Stash notes erased: failed read → next ADD/delete saves only the new note | inventory.py:44-46, save() 79 | yes |
| 4 | Non-UTF-8 inventory.json crashes start-up | inventory.py:44 | yes |
| 5 | Blueprint registry erased on the next log event after a failed read | blueprints.py:315-318, _process 738 | yes |
| 6 | Ore-finder cache with changed fields crashes start-up (TypeError outside the try) | orefinder.py:332-344 | yes |
| 7 | Tracking pin dropped when a monitor only moves (same resolution) | main.py:1076-1079, 1094-1095 | yes |
| 8 | UPDATE hand-off waits only 60 s; a slow exit → Setup stops (AppMutex), nothing restarts | updater.py:222 | code yes; slow exit unverified |
| 9 | TRACKING slider re-saves config.json on almost every pixel of a drag | ui/settings_panel.py _on_tracking, main.py _on_tracking | two reviewers |
| 10 | KILLS/DEATHS count every kill line, not the player's own | combat.py:591-596 | yes |

## Other warnings (reviewer reports, not each re-checked)
- Update: download checked by size + "MZ" only (GitHub gives sha256 digests);
  version text can differ from what downloads; update thread not waited at quit.
- Anchor load/calibration errors are shown as "No pin icon found".
- OpenCV/numpy now import on the GUI thread at start-up when a pin is saved.
- tracking_range parsed two ways (crash on a hand-edited string).
- Scan cache keeps old matches after tolerance/data reload on a static screen.
- SHOW BOX outline: full re-placement + 3 timers per tracking move; _enforce
  could ping-pong at some scales (unverified); picker repaints the whole 5K
  window per mouse move.
- Game.log tailers: LIVE always preferred over PTU (cached forever); first
  lines of a new log skipped (game_log, refinery); a parser exception kills the
  tailer thread; half-written lines parsed as whole lines.
- Blueprints: unbounded event_queue; registry rewritten on every loot event.
- Hauling: switching commodity during a fetch drops the new fetch; quit can
  wait 30-60 s and abort with "QThread destroyed while running".
- Ore finder: in-place sort on a worker thread; workers not stopped at quit.
- Hotkeys: RegisterHotKey on bare F4 may take the key from the game (unverified).
- Settings: some programmatic setters don't block signals; hard-coded pixel
  sizes ignore UI scale; windows open on the primary rather than the game monitor.

## Genuinely fine
ScanThread cross-thread design (atomic tuple swap, GUI-only Qt calls);
PowerShell quoting in the updater; tracking maths and clipping; picker and
outline lifetimes; voice, marketplace, stations, mining data, UEX panel, combat
panel and event bus; hauling network calls (timeouts, off the GUI thread).

## Quality-of-life ideas (from the reviewers)
- Safe shared JSON/text store: refuse to overwrite after a failed read, keep a
  .bak, retry Windows file locks, show "not loaded" (fixes 1-5 at once).
- Follow the Game.log actually being written (LIVE/PTU/EPTU), show which.
- Rebindable hotkeys in Settings (frees F4), hotkeys to open panels.
- Honest data age ("2 h ago", amber when stale) in Hauling/Combat.
- One shared Game.log tailer instead of 3-4 threads.
- Remember planner inputs (capital, filters, cargo per ship).
- Real K/D from the player's own handle; session reset.
- Picker: right-click cancels, arrow keys nudge 1 px, loupe on high DPI.
- Re-learn the pin after a resolution change; preview the search area while
  the plate is lost; validate config types at load.
- First-run guidance when no region is set.
