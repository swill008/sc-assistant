"""The scanner settings survive QUIT and a restart.

    python -m tools.settings_persist_selftest

Runs the real OverlayApp twice against a temporary settings folder (your own
%APPDATA% is never touched). The first run changes READS / S, TRACKING, SHOW
BOX and MONITOR through the Settings controls, saves a pin and plate from the 5K2K test
image the way DRAW REGION does, and quits with QUIT. The file on disk must hold
every change; the second run, started from that file, must show each one in
Settings and use it in the scanner. The open Settings sections (headings
opened and closed in the first run) must come back the same, an unknown id in
the file is dropped, and SCANNER is forced open only while no box is drawn. The DEBUG switches (SCAN HISTORY, SAVE
BAD READS, DETAILED LOG) are turned on by clicks and come back on, and the
VIEW LOG window opens where it was left. A third run uses UNMATCHED READINGS (OPEN
FOLDER, CLEAR) and RESET SETTINGS: the restart is caught, the settings file
must stay gone after the restart and quit (nothing old written back), a dated
backup holds it, scan_history.txt and bad_reads/ are removed, DETAILED LOG goes
off, app.log is kept and the log window closes, and a fourth run starts on the
defaults (the DEBUG switches off). Each run reads its settings the way main()
does (main._startup_config: app.log first).

VOICE (first run, fake Windows and Piper engines put into the real Voice so
nothing is spoken or downloaded): ENGINE lists the voices of the chosen
engine, DOWNLOAD shows the size and progress and CANCEL stops it, a second
DOWNLOAD finishes, TEST speaks the test phrase in the SAYS style at the chosen
voice, speed and volume 0; then ENGINE Microsoft online, a voice, SPEED and SAYS
are saved, come back in the second run (menu and Voice), and the reset run
starts on the Windows defaults.
"""
from __future__ import annotations

from tools import _testguard

_testguard.install()        # first: no focus, no hotkeys

import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_TMP = tempfile.TemporaryDirectory(prefix="ca-persist-")
os.environ["APPDATA"] = _TMP.name          # before app.config is imported
os.environ["LOCALAPPDATA"] = _TMP.name     # voice add-ons and caches (app.tts)

import cv2  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

FIXTURE = ROOT / "tools" / "fixtures" / "signal_42000_5k2k.png"
DIGITS = (76, 38, 56, 28)                   # the digits box inside the fixture


def _check(label: str, ok: bool, detail: str = "") -> int:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{'  ' + detail if detail else ''}")
    return 0 if ok else 1


def _user_opens(s, ids: list) -> None:
    """Click the Settings headings whose open state differs from ids (a
    forced heading ignores the click, as it does for the user)."""
    from PySide6.QtTest import QTest

    from app.ui.settings_panel import SECTION_IDS

    for sid in SECTION_IDS:
        if (sid in ids) != (sid in s.open_sections):
            QTest.mouseClick(s.section_header(sid), Qt.MouseButton.LeftButton)
    QApplication.processEvents()


def _hide_log_viewer_windows() -> None:
    """VIEW LOG windows in this test are see-through (the real LogViewer)."""
    from app import main as main_mod
    from app.ui.log_viewer import LogViewer

    class _SeeThrough(LogViewer):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.setWindowOpacity(0.0)
    main_mod.LogViewer = _SeeThrough


def _startup():
    """The settings as main() reads them: app.log first, then config.json,
    then DETAILED LOG (main._startup_config)."""
    from app import main as main_mod

    return main_mod._startup_config()


def _pump(seconds: float) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        QApplication.processEvents()
        time.sleep(0.01)


class _FakeWindowsVoices:
    """Stands in for the Windows voices: records speak(), says nothing."""

    id = "windows"
    label = "Windows voices (built in, offline)"
    note = ""
    online = False
    speaks_directly = True

    def __init__(self):
        self.spoken: list = []

    def available(self):
        return True

    def unavailable_reason(self):
        return ""

    def voices(self):
        from app.tts.base import Voice as VoiceInfo
        return [VoiceInfo("fake:A", "Fake A", "winrt · en-US"),
                VoiceInfo("fake:B", "Fake B", "sapi · en-GB")]

    def default_voice(self):
        return "fake:A"

    def needs_download(self, voice_id):
        return 0

    def download(self, voice_id, progress=None, cancelled=None):
        return None

    def speak(self, text, voice_id, speed, volume):
        self.spoken.append((text, voice_id, speed, volume))
        return True

    def set_volume(self, volume):
        pass

    def stop(self):
        pass


class _FakePiper(_FakeWindowsVoices):
    """An add-on engine whose voices need a download (no network)."""

    id = "piper"
    label = "Piper (offline, natural · add-on, GPL-3.0)"
    note = "Add-on, GPL-3.0 (fake engine)"
    speaks_directly = False
    SIZE = 40 << 20

    def __init__(self):
        super().__init__()
        self.ready: set = set()
        self.calls: list = []

    def voices(self):
        from app.tts.base import Voice as VoiceInfo
        return [VoiceInfo("p1", "Piper One", "CC0 · 40 MB"),
                VoiceInfo("p2", "Piper Two", "CC-BY · 40 MB")]

    def default_voice(self):
        return "p1"

    def needs_download(self, voice_id):
        return 0 if voice_id in self.ready else self.SIZE

    def download(self, voice_id, progress=None, cancelled=None):
        from app.tts.base import Cancelled
        self.calls.append(voice_id)
        steps = 40
        for i in range(steps + 1):
            if cancelled is not None and cancelled():
                raise Cancelled()
            if progress is not None:
                progress(self.SIZE * i // steps, self.SIZE)
            time.sleep(0.03)
        self.ready.add(voice_id)


def _wait(cond, seconds: float = 5.0) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        QApplication.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return cond()


def _pick(box, data) -> None:
    """Choose an entry of a Settings list the way a click does."""
    index = box.findData(data)
    box.setCurrentIndex(index)
    box.activated.emit(index)
    QApplication.processEvents()


def _voice_first_run(one) -> tuple[int, dict]:
    """VOICE through the Settings controls on fake engines; returns
    (failures, what should be saved)."""
    from PySide6.QtTest import QTest

    from app.tts import phrases

    failures = 0
    s = one.settings
    fake_win, fake_piper = _FakeWindowsVoices(), _FakePiper()
    one.voice._engines["windows"] = fake_win
    one.voice._engines["piper"] = fake_piper
    one._show_voice_menu()
    s.volume_slider.setValue(0)                 # TEST below at volume 0

    engines = [s.engine_box.itemData(i) for i in range(s.engine_box.count())]
    failures += _check("VOICE: ENGINE lists windows, piper, kokoro, edge",
                       engines == ["windows", "piper", "kokoro", "edge"], f"({engines})")
    failures += _check("VOICE: Windows shows its voices, default first",
                       s.voice_id == "fake:A" and s.voice_box.count() == 2
                       and s.voice_download_row.isHidden(), f"({s.voice_id!r})")

    _pick(s.engine_box, "piper")
    failures += _check("VOICE: choosing Piper lists Piper's voices and is used",
                       [s.voice_box.itemData(i) for i in range(s.voice_box.count())] == ["p1", "p2"]
                       and one.voice.engine_id == "piper" and one.cfg["voice_engine"] == "piper"
                       and one.voice.voice_id == "p1",
                       f"({one.voice.engine_id}, {one.voice.voice_id!r})")
    failures += _check("VOICE: DOWNLOAD shows the size, TEST waits",
                       not s.voice_download_row.isHidden()
                       and s.voice_download_label.text() == "Needs a 40 MB download"
                       and not s.voice_test_btn.isEnabled(), f"({s.voice_download_label.text()!r})")
    failures += _check("VOICE: the note is the engine's own (licence)",
                       "GPL-3.0" in s.voice_note.text(), f"({s.voice_note.text()!r})")

    QTest.mouseClick(s.voice_download_btn, Qt.MouseButton.LeftButton)
    moving = _wait(lambda: s.voice_download_label.text().startswith(("5%", "7%", "1", "2")), 5.0)
    failures += _check("VOICE: DOWNLOAD shows progress 'NN% · got of total MB' and CANCEL",
                       moving and " of 40 MB" in s.voice_download_label.text()
                       and s.voice_download_btn.text() == "CANCEL"
                       and "downloading" in s.section_summary("voice"),
                       f"({s.voice_download_label.text()!r}, {s.voice_download_btn.text()!r})")
    QTest.mouseClick(s.voice_download_btn, Qt.MouseButton.LeftButton)
    stopped = _wait(lambda: one._voice_download is None, 5.0)
    failures += _check("VOICE: CANCEL stops the download; DOWNLOAD is back",
                       stopped and "p1" not in fake_piper.ready
                       and s.voice_download_btn.text() == "DOWNLOAD"
                       and "Download cancelled" in s.voice_note.text(),
                       f"({s.voice_note.text()!r})")

    QTest.mouseClick(s.voice_download_btn, Qt.MouseButton.LeftButton)
    done = _wait(lambda: one._voice_download is None and "p1" in fake_piper.ready, 8.0)
    failures += _check("VOICE: a second DOWNLOAD finishes: row hidden, TEST back, note says so",
                       done and s.voice_download_row.isHidden() and s.voice_test_btn.isEnabled()
                       and "Downloaded" in s.voice_note.text() and fake_piper.calls == ["p1", "p1"],
                       f"({fake_piper.calls}, {s.voice_note.text()!r})")

    # TEST on the (fake) Windows voices, second voice, 1.4x, with the reading.
    _pick(s.engine_box, "windows")
    _pick(s.voice_box, "fake:B")
    s.speed_slider.setValue(14)
    _pick(s.style_box, "with_signature")
    QTest.mouseClick(s.voice_test_btn, Qt.MouseButton.LeftButton)
    want = phrases.test_phrase("with_signature")
    failures += _check("VOICE: TEST says the test phrase in the SAYS style, chosen voice, "
                       "speed, volume 0",
                       fake_win.spoken[-1:] == [(want, "fake:B", 1.4, 0.0)]
                       and want == "Feynmaline, nineteen deposits, fifty-seven thousand",
                       f"({fake_win.spoken})")

    # What is saved: the real Microsoft online engine (its built-in voice list).
    _pick(s.engine_box, "edge")
    edge_ids = [s.voice_box.itemData(i) for i in range(s.voice_box.count())]
    choice = edge_ids[1] if len(edge_ids) > 1 else (edge_ids[0] if edge_ids else "")
    if choice:
        _pick(s.voice_box, choice)
    failures += _check("VOICE: Microsoft online lists voices with no download",
                       len(edge_ids) >= 2 and s.voice_download_row.isHidden()
                       and "Microsoft" in s.voice_note.text(),
                       f"({edge_ids[:3]}, {s.voice_note.text()!r})")
    want_saved = {"voice_engine": "edge", "voice_voice": choice, "voice_speed": 1.4,
                  "voice_style": "with_signature", "voice_volume": 0.0}
    got = {k: one.cfg[k] for k in want_saved}
    failures += _check("VOICE: the choices are in the settings", got == want_saved, f"({got})")
    return failures, want_saved


def _reset_run(app, saved: dict) -> int:
    """Third run: UNMATCHED READINGS buttons, then RESET SETTINGS (two clicks).
    The restart is caught (no process is started); the settings file must be
    gone after the restart and quit, a dated backup must hold the old one, and
    the next start must use the defaults."""
    from app import config as app_config
    from app import main as main_mod
    from app.config import CONFIG_PATH, DEFAULTS, config_dir
    from app.main import OverlayApp

    failures = 0
    print("Third run: UNMATCHED READINGS, then RESET SETTINGS")
    three = OverlayApp(app, _startup())
    three.start()
    three.panel.hide()
    _pump(0.5)
    s = three.settings
    if not hasattr(s, "reset_btn") or not hasattr(three, "unmatched"):
        return _check("RESET SETTINGS and UNMATCHED READINGS are wired", False)

    opened: list = []
    real_open, real_popen = app_config.open_folder, main_mod.subprocess.Popen
    app_config.open_folder = opened.append
    launched: list = []
    main_mod.subprocess.Popen = lambda args, **kw: launched.append(list(args))
    try:
        three.unmatched.record(9999, "unknown", None)
        three._show_unmatched()
        s.unmatched_open_btn.click()
        failures += _check("OPEN FOLDER opens the unmatched folder",
                           opened == [config_dir() / "unmatched"], f"(opened {opened})")
        s.unmatched_clear_btn.click()
        s.unmatched_clear_btn.click()
        failures += _check("CLEAR (two clicks) empties the unmatched readings",
                           three.unmatched.entries() == [], f"({three.unmatched.entries()})")

        # DEBUG files on disk (both switches on from the first run).
        import numpy as np

        history = getattr(three, "_history", None)
        if history is not None:
            history.add("one read")
            three._flush_history()
        main_mod.save_bad_read(config_dir() / "bad_reads", np.zeros((20, 50, 3), np.uint8),
                               time.time(), {"state": "locked", "digits": None}, 1)
        failures += _check("DEBUG files exist before the reset",
                           (config_dir() / "scan_history.txt").is_file()
                           and any((config_dir() / "bad_reads").glob("*.png")))

        from app import applog

        s.log_view_btn.click()
        viewer = three._log_viewer
        failures += _check("before the reset: DETAILED LOG on, log window open",
                           applog.detailed() and viewer is not None and viewer.isVisible())
        s.reset_btn.click()
        _pump(0.1)
        failures += _check("one RESET click keeps the settings", CONFIG_PATH.is_file() and not launched)
        s.reset_btn.click()
        _pump(0.5)
        three.save_config()                # what main()'s aboutToQuit hook runs
    finally:
        app_config.open_folder, main_mod.subprocess.Popen = real_open, real_popen
    failures += _check("second RESET click restarts the app",
                       len(launched) == 1 and "--restart" in launched[0], f"(launched {launched})")
    failures += _check("reset stopped the scanner", three.scan.isFinished())
    failures += _check("restart and quit wrote no settings back (no config.json)",
                       not CONFIG_PATH.is_file(),
                       f"({CONFIG_PATH.read_text(encoding='utf-8')[:80] if CONFIG_PATH.is_file() else ''})")
    failures += _check("pin removed", not (config_dir() / "anchor.png").is_file())
    log_text = ((config_dir() / "app.log").read_text(encoding="utf-8")
                if (config_dir() / "app.log").is_file() else "")
    failures += _check("reset: DETAILED LOG off, log window closed, app.log kept",
                       not applog.detailed() and not viewer.isVisible()
                       and "RESET SETTINGS: starting" in log_text,
                       f"({sorted(p.name for p in config_dir().iterdir())})")
    failures += _check("reset removed scan_history.txt and bad_reads/",
                       not (config_dir() / "scan_history.txt").exists()
                       and not (config_dir() / "bad_reads").exists(),
                       f"({sorted(p.name for p in config_dir().iterdir())})")
    folder = config_dir()
    backups = [p for p in folder.parent.iterdir() if p.name.startswith(f"{folder.name} backup ")]
    kept = [json.loads((b / "config.json").read_text(encoding="utf-8")) for b in backups
            if (b / "config.json").is_file()]
    failures += _check("a dated backup holds the old settings",
                       any(k.get("poll_ms") == saved.get("poll_ms") for k in kept), f"(backups {backups})")
    three.outline.hide()
    for w in (three.nav, three.panel, three.settings):
        w.hide()

    print("Fourth run: start after the reset")
    four = OverlayApp(app, _startup())
    four.start()
    four.panel.hide()
    _pump(0.5)
    failures += _check("READS / S back to the default",
                       four.scan._interval == int(DEFAULTS["poll_ms"]), f"(interval {four.scan._interval})")
    failures += _check("no box and no pin after the reset",
                       four.cfg["region"] == DEFAULTS["region"] and not four.scan.tracking)
    failures += _check("DEBUG switches back to off",
                       four.cfg.get("debug_scan_history") is False
                       and four.cfg.get("debug_save_bad_reads") is False
                       and not four.settings.history_btn.isChecked()
                       and not four.settings.bad_reads_btn.isChecked()
                       and four.cfg.get("debug_detailed_log") is False
                       and not four.settings.detailed_log_btn.isChecked()
                       and getattr(four, "_history", "missing") is None)
    failures += _check("open Settings sections back to SCANNER only",
                       four.cfg["settings_open"] == ["scanner"] and four.settings.open_sections == ["scanner"],
                       f"(cfg {four.cfg['settings_open']}, panel {four.settings.open_sections})")
    s4 = four.settings
    failures += _check("VOICE back to the Windows defaults (engine, speed, says, volume)",
                       (four.cfg["voice_engine"], four.cfg["voice_speed"], four.cfg["voice_style"],
                        four.cfg["voice_volume"]) == ("windows", 1.0, "count_after", 0.8)
                       and (four.voice.engine_id, four.voice.speed, four.voice.style)
                       == ("windows", 1.0, "count_after")
                       and (s4.voice_engine, s4.voice_speed, s4.voice_style)
                       == ("windows", 1.0, "count_after")
                       and s4.volume_slider.value() == 80,
                       f"(cfg {four.cfg['voice_engine']}/{four.cfg['voice_speed']}/"
                       f"{four.cfg['voice_style']}, panel {s4.voice_engine}/{s4.voice_speed})")
    four.nav.quit_btn.click()
    four.nav.quit_btn.click()
    _pump(0.3)
    return failures


def main() -> int:
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication.instance() or QApplication(sys.argv)
    _hide_log_viewer_windows()

    from app import applog, display
    from app.config import CONFIG_PATH, Config, config_dir
    from app.main import OverlayApp
    from app.ui.settings_panel import TRACKING_STEP

    failures = 0
    screens = QGuiApplication.screens()
    primary = QGuiApplication.primaryScreen()
    # Start on a secondary monitor so nothing covers the game; switch to
    # another monitor through the MONITOR list.
    start = next((s for s in screens if s is not primary), primary)
    others = [s for s in screens if s is not start]
    other = next((s for s in others if s is not primary), others[0] if others else None)
    mon = display.physical_rect(start)
    region = {"left": mon["left"] + mon["width"] // 2, "top": mon["top"] + mon["height"] // 2,
              "width": DIGITS[2], "height": DIGITS[3]}
    cfg = Config()
    cfg["region"] = region
    cfg["region_monitor"] = mon
    cfg["game_monitor"] = start.name()
    cfg["voice_enabled"] = False
    cfg["nav_visible"] = False            # keep the nav bar off the game screen
    cfg.save()
    print(f"settings folder {config_dir()}")
    print("-" * 78)

    # ---- first run: change everything through the UI, then QUIT ----------
    print("First run: change the settings, then QUIT")
    one = OverlayApp(app, _startup())
    one.start()
    one.panel.hide()                      # the scanner panel opens on the main screen
    _pump(0.5)
    s = one.settings
    want_monitor = other.name() if other is not None else start.name()
    if other is not None:
        s.monitor_box.setCurrentIndex(s.monitor_box.findData(other.name()))
        s.monitor_box.activated.emit(s.monitor_box.currentIndex())
    s.reads_slider.setValue(6)
    s.tracking_slider.setValue(250 // TRACKING_STEP)  # the slider counts 50 px steps
    s.outline_btn.setChecked(True)
    if hasattr(s, "history_btn"):
        s.history_btn.click()
        s.bad_reads_btn.click()
    # Logs: DETAILED LOG on (level switches at once); VIEW LOG opens one
    # window, moved by the user, its place saved like the other windows.
    s.detailed_log_btn.click()
    failures += _check("DETAILED LOG click switches the log level at once", applog.detailed())
    sg = start.availableGeometry()
    one.cfg["logviewer_pos"] = [sg.left() + 40, sg.top() + 40]   # on the test monitor
    s.log_view_btn.click()
    viewer = one._log_viewer
    s.log_view_btn.click()
    failures += _check("VIEW LOG opens one log window on app.log",
                       viewer is not None and one._log_viewer is viewer and viewer.isVisible()
                       and viewer.path == applog.log_path())
    viewer.move(sg.left() + 70, sg.top() + 55)
    want_viewer = [viewer.x(), viewer.y()]
    _pump(1.3)                            # the debounced window save
    voice_failures, want_voice = _voice_first_run(one)
    failures += voice_failures
    want_open = ["scanner", "hotkeys", "look"]
    _user_opens(s, want_open)
    # DRAW REGION on the new box (the digits of the 5K2K image, which works on
    # any monitor height), its screen faked: the pin, digits box and plate.
    box = dict(one.cfg["region"], width=DIGITS[2], height=DIGITS[3])
    one.cfg["region"] = dict(box)
    image = cv2.imread(str(FIXTURE))
    origin = (box["left"] - DIGITS[0], box["top"] - DIGITS[1])

    def grab(rect):
        import numpy as np

        out = np.zeros((int(rect["height"]), int(rect["width"]), 3), np.uint8)
        x, y = origin[0] - rect["left"], origin[1] - rect["top"]
        ih, iw = image.shape[:2]
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(out.shape[1], x + iw), min(out.shape[0], y + ih)
        out[y0:y1, x0:x1] = image[y0 - y:y1 - y, x0 - x:x1 - x]
        return out
    one._calibrate_drawn(dict(box), grab=grab)
    _pump(1.0)
    failures += _check("pin and plate saved from the 5K2K image by DRAW REGION",
                       bool(one.cfg["anchor"]) and bool(one.cfg.get("plate")),
                       f"(anchor {one.cfg['anchor']}, plate {one.cfg.get('plate')})")
    box_after = dict(one.cfg["region"])
    _pump(0.3)
    one.nav.quit_btn.click()
    one.nav.quit_btn.click()
    _pump(0.5)
    failures += _check("QUIT stopped the first run", one.scan.isFinished())

    saved = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    print("Saved file after QUIT")
    failures += _check("READS / S 6 saved", saved.get("poll_ms") == round(1000 / 6), f"(poll_ms {saved.get('poll_ms')})")
    failures += _check("TRACKING ±250 saved", saved.get("tracking_range") == 250, f"({saved.get('tracking_range')})")
    failures += _check("SHOW BOX on saved", saved.get("show_region_outline") is True, f"({saved.get('show_region_outline')})")
    failures += _check("MONITOR choice saved", saved.get("game_monitor") == want_monitor, f"({saved.get('game_monitor')!r})")
    failures += _check("box saved", saved.get("region") == box_after, f"({saved.get('region')})")
    meta = saved.get("anchor")
    failures += _check("pin saved", bool(meta) and (config_dir() / meta.get("file", "")).is_file(), f"({meta})")
    failures += _check("plate saved", saved.get("plate") == one.cfg.get("plate") and bool(saved.get("plate")),
                       f"({saved.get('plate')})")
    failures += _check("DEBUG switches saved on",
                       saved.get("debug_scan_history") is True and saved.get("debug_save_bad_reads") is True,
                       f"({saved.get('debug_scan_history')}, {saved.get('debug_save_bad_reads')})")
    failures += _check("open Settings sections saved", saved.get("settings_open") == want_open,
                       f"({saved.get('settings_open')})")
    got_voice = {k: saved.get(k) for k in want_voice}
    failures += _check("VOICE choices saved (engine, voice, speed, says, volume)",
                       got_voice == want_voice, f"({got_voice})")
    failures += _check("DETAILED LOG and the log window place saved",
                       saved.get("debug_detailed_log") is True
                       and saved.get("logviewer_pos") == want_viewer,
                       f"({saved.get('debug_detailed_log')}, {saved.get('logviewer_pos')} vs {want_viewer})")
    failures += _check("QUIT closed the log window", not viewer.isVisible())
    # A hand-edited or older file may name a section that no longer exists.
    edited = dict(saved, settings_open=want_open + ["no_such_section"])
    CONFIG_PATH.write_text(json.dumps(edited, indent=2), encoding="utf-8")
    one.outline.hide()
    for w in (one.nav, one.panel, one.settings):
        w.hide()

    # ---- second run: started from the saved file ------------------------
    print("Second run: start from the saved file")
    two = OverlayApp(app, _startup())
    two.start()
    two.panel.hide()
    _pump(0.8)
    s = two.settings
    failures += _check("READS / S shows 6", s.reads_slider.value() == 6 and s.reads_label.text() == "6 / s",
                       f"(slider {s.reads_slider.value()}, label {s.reads_label.text()!r})")
    failures += _check("scanner reads 6 times a second", two.scan._interval == round(1000 / 6),
                       f"(interval {two.scan._interval} ms)")
    failures += _check("TRACKING shows ±250 px", s.tracking_value == 250 and s.tracking_label.text() == "±250 px",
                       f"(value {s.tracking_value}, label {s.tracking_label.text()!r})")
    failures += _check("SHOW BOX shows on", s.outline_btn.isChecked())
    failures += _check("outline is shown", two.outline.isVisible())
    failures += _check("MONITOR shows the saved monitor", s.monitor_box.currentData() == want_monitor,
                       f"({s.monitor_box.currentData()!r})")
    failures += _check("scanner uses the saved box", two.scan._region == box_after, f"({two.scan._region})")
    failures += _check("saved pin loaded: tracking is on", two.scan.tracking)
    want_plate = tuple(saved.get("plate", {}).get(k) for k in ("dx", "dy", "w", "h"))
    failures += _check("saved plate handed to the scanner (preview of the whole window)",
                       getattr(two.scan, "_plate", None) == want_plate,
                       f"(scanner {getattr(two.scan, '_plate', '<missing>')}, saved {want_plate})")
    failures += _check("no amber note", not s.region_note.text(), f"({s.region_note.text()!r})")
    failures += _check("DEBUG switches show on and SCAN HISTORY records",
                       getattr(s, "history_btn", None) is not None and s.history_btn.isChecked()
                       and s.bad_reads_btn.isChecked()
                       and s.section_summary("debug") == "history on · saver on · log detailed"
                       and getattr(two, "_history", None) is not None)
    failures += _check("DETAILED LOG comes back on (switch and level)",
                       s.detailed_log_btn.isChecked() and applog.detailed())
    s.log_view_btn.click()
    failures += _check("VIEW LOG opens where it was left",
                       two._log_viewer is not None
                       and [two._log_viewer.x(), two._log_viewer.y()] == want_viewer,
                       f"({two._log_viewer.pos() if two._log_viewer else None} vs {want_viewer})")
    failures += _check("VOICE comes back in the menu (engine, voice, speed, says, volume)",
                       (s.voice_engine, s.voice_id, s.voice_speed, s.voice_style,
                        s.volume_slider.value())
                       == ("edge", want_voice["voice_voice"], 1.4, "with_signature", 0),
                       f"({s.voice_engine}, {s.voice_id!r}, {s.voice_speed}, {s.voice_style})")
    failures += _check("VOICE comes back in the Voice used for announcements",
                       (two.voice.engine_id, two.voice.voice_id, two.voice.speed, two.voice.style,
                        two.voice.volume)
                       == ("edge", want_voice["voice_voice"], 1.4, "with_signature", 0.0))
    failures += _check("VOICE summary: off · Microsoft online · <voice> · 1.4×",
                       s.section_summary("voice").startswith("off · Microsoft online · ")
                       and s.section_summary("voice").endswith(" · 1.4×"),
                       f"({s.section_summary('voice')!r})")
    failures += _check("open Settings sections come back, unknown id dropped",
                       s.open_sections == want_open and two.cfg["settings_open"] == want_open,
                       f"(panel {s.open_sections}, cfg {two.cfg['settings_open']})")
    _user_opens(s, ["hotkeys", "look"])
    failures += _check("box drawn: SCANNER can be closed", s.open_sections == ["hotkeys", "look"],
                       f"({s.open_sections})")
    _user_opens(s, want_open)
    two.nav.quit_btn.click()
    two.nav.quit_btn.click()
    _pump(0.5)
    resaved = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    failures += _check("quitting again keeps every setting",
                       all(resaved.get(k) == saved.get(k) for k in
                           ("poll_ms", "tracking_range", "show_region_outline", "game_monitor", "region", "anchor", "plate",
                            "settings_open", "debug_scan_history", "debug_save_bad_reads",
                            "debug_detailed_log", "logviewer_pos", "voice_engine",
                            "voice_voice", "voice_speed", "voice_style", "voice_volume")))

    # ---- RESET SETTINGS: defaults after the restart, nothing written back --
    failures += _reset_run(app, saved)

    # ---- fresh start with no region: no picker forced on screen ----------
    print("Fresh start, no region saved")
    for name in ("config.json", "anchor.png"):
        (config_dir() / name).unlink(missing_ok=True)
    fresh_cfg = Config()
    fresh_cfg["nav_visible"] = False
    fresh_cfg["voice_enabled"] = False
    fresh_cfg.save()
    three = OverlayApp(app, Config.load())
    notes: list[str] = []
    show_idle = three.panel.set_scan_idle
    three.panel.set_scan_idle = lambda note="": (notes.append(note), show_idle(note))
    three.start()
    three.panel.hide()
    _pump(1.5)                            # the old build opened the picker after 0.65 s
    failures += _check("no region picker opened at start-up", three._selector is None)
    failures += _check("panel says to press DRAW REGION", any("DRAW REGION" in n for n in notes), f"({notes})")
    s = three.settings
    _user_opens(s, ["hotkeys"])
    failures += _check("no box: SCANNER stays open when its heading is closed",
                       s.open_sections == ["scanner", "hotkeys"], f"({s.open_sections})")
    three._apply_region(region, mon, start.name())
    _user_opens(s, ["hotkeys"])
    failures += _check("box applied: SCANNER released and can be closed",
                       s.open_sections == ["hotkeys"], f"({s.open_sections})")
    three.nav.quit_btn.click()
    three.nav.quit_btn.click()
    _pump(0.3)

    print("-" * 78)
    print("ALL CHECKS PASSED" if failures == 0 else f"{failures} CHECK(S) FAILED")
    import logging
    logging.shutdown()                    # app.log closed: the temp folder can go
    return failures


if __name__ == "__main__":
    raise SystemExit(main())
