"""UPDATE button and the Settings controls around it.

    python -m tools.update_selftest

Release lookup, sha256-checked download, "What's new", the installed-EXE
flow, standalone copies, the installer hand-off command (run for real against
a fake Setup), the TRACKING slider and the setters that must not echo.

Uses fakes for everything that would download or install, plus one live,
read-only request for the fork's latest release. The real hand-off with the
real Setup is checked by installer\\test_installer.ps1 -NewerSetup.
"""
from __future__ import annotations

from tools import _testguard

_testguard.install()        # first: no focus, no hotkeys

import hashlib
import io
import os
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_TMP = tempfile.TemporaryDirectory(prefix="sca-update-")
os.environ["APPDATA"] = _TMP.name          # before app.config is imported

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app import updater  # noqa: E402
from app import version  # noqa: E402

NOTES = """## What's new in 9.9.10
### Fixed
- **UPDATE** waits for the old version <script>alert(1)</script> to close
- See [the notes](https://example.com/notes)

## How to install
- Run the installer
"""


def _check(label: str, ok: bool, detail: str = "") -> int:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{'  ' + detail if detail else ''}")
    return 0 if ok else 1


def _wait(cond, seconds: float = 5.0) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        QApplication.processEvents()
        if cond():
            return True
        time.sleep(0.02)
    return cond()


class _Patch:
    """Swap module attributes for the duration of a with-block."""

    def __init__(self, target, **values):
        self.target, self.values, self.saved = target, values, {}

    def __enter__(self):
        for k, v in self.values.items():
            self.saved[k] = getattr(self.target, k)
            setattr(self.target, k, v)
        return self

    def __exit__(self, *exc):
        for k, v in self.saved.items():
            setattr(self.target, k, v)


def _release(version="9.9.9", url="u", size=1, digest="", body=""):
    make = getattr(updater, "Release", None)
    return make(version, url, size, digest, body) if make else (version, url, size)


def check_release_parsing() -> int:
    failures = 0
    release = {"tag_name": "v1.2.20", "body": NOTES, "assets": [
        {"name": "SCAssistant-windows-x64.zip", "browser_download_url": "https://x/zip", "size": 1},
        {"name": "SCAssistant-1.2.20-TEST-Setup.exe", "browser_download_url": "https://x/test", "size": 2},
        {"name": "SCAssistant-1.2.20-Setup.exe", "browser_download_url": "https://x/setup", "size": 3,
         "digest": "sha256:abc"},
    ]}
    found = updater.setup_asset(release)
    failures += _check("picks the release's Setup.exe (not the zip or a TEST edition), with digest and notes",
                       found == ("1.2.20", "https://x/setup", 3, "sha256:abc", NOTES),
                       f"({found!r:.80})")
    failures += _check("Release has named fields",
                       getattr(found, "digest", None) == "sha256:abc" and getattr(found, "body", None) == NOTES)
    failures += _check("no installer in a release -> None",
                       updater.setup_asset({"assets": [release["assets"][0]]}) is None)
    with _Patch(updater, is_frozen=lambda: True, latest_release=lambda t=15.0: _release("9.9.9"),
                published_version=lambda t=15.0: "0.0.1"):
        failures += _check("installed EXE: CHECK uses the latest release", updater.newest()[1:] == ("9.9.9", True))
        failures += _check("installed EXE: check() gives the release notes",
                           updater.check() == ("9.9.9", ""))
    with _Patch(updater, is_frozen=lambda: False, latest_release=lambda t=15.0: _release("9.9.9", body=NOTES),
                published_version=lambda t=15.0: "0.0.1"):
        failures += _check("source install: CHECK still uses main's version.py", updater.newest()[1] == "0.0.1")
        failures += _check("source install: no notes from a different release", updater.check() == ("0.0.1", ""))
    here = Path(sys.executable).resolve().parent
    with _Patch(updater, is_frozen=lambda: True, _install_location=lambda: here):
        failures += _check("EXE in the installed folder is not standalone", not updater.standalone())
    with _Patch(updater, is_frozen=lambda: True, _install_location=lambda: None):
        failures += _check("EXE with no install entry is standalone", updater.standalone())
    with _Patch(updater, is_frozen=lambda: True, _install_location=lambda: Path(_TMP.name)):
        failures += _check("EXE outside the installed folder is standalone", updater.standalone())
    with _Patch(updater, is_frozen=lambda: False):
        failures += _check("source install is never standalone", not updater.standalone())
    return failures


def check_names() -> int:
    """The 1.0.0 rename: repository, User-Agent, Setup and archive names."""
    failures = 0
    failures += _check("updater uses the renamed repository swill008/sc-assistant",
                       updater.REPO == version.REPO == "swill008/sc-assistant"
                       and "/swill008/sc-assistant/" in updater.ARCHIVE
                       and "/repos/swill008/sc-assistant/" in updater.LATEST_RELEASE
                       and updater.RELEASES_PAGE == "https://github.com/swill008/sc-assistant/releases",
                       f"({updater.REPO}, {updater.LATEST_RELEASE})")
    failures += _check("User-Agent names SC Assistant and the new repository",
                       updater.USER_AGENT == version.USER_AGENT
                       and updater.USER_AGENT.startswith(f"SC-Assistant/{version.VERSION} ")
                       and "github.com/swill008/sc-assistant" in updater.USER_AGENT,
                       f"({updater.USER_AGENT})")

    def pick(*names):
        found = updater.setup_asset({"assets": [
            {"name": n, "browser_download_url": f"https://x/{n}", "size": 1} for n in names]})
        return found.version if found else None
    failures += _check("accepts SCAssistant-1.0.1-Setup.exe", pick("SCAssistant-1.0.1-Setup.exe") == "1.0.1")
    failures += _check("ignores the old CitizenAssistant-1.2.19-Setup.exe",
                       pick("CitizenAssistant-1.2.19-Setup.exe") is None)
    failures += _check("picks the new Setup next to an old one",
                       pick("CitizenAssistant-1.2.19-Setup.exe", "SCAssistant-1.0.1-Setup.exe") == "1.0.1")
    failures += _check("ignores a TEST edition and look-alikes",
                       pick("SCAssistant-1.0.1-TEST-Setup.exe", "XSCAssistant-1.0.1-Setup.exe",
                            "SCAssistant-1.0.1-Setup.exe.part") is None)
    failures += _check("source update copies sc-assistant.spec, not the old spec",
                       "sc-assistant.spec" in updater.COPY_FILES
                       and "citizen-assistant.spec" not in updater.COPY_FILES)
    top = getattr(updater, "archive_top", None)
    if top is None:
        return failures + _check("archive_top accepts any single top folder", False, "(missing)")
    base = Path(_TMP.name) / "archive"
    for name in ("sc-assistant-main", "anything-else"):
        folder = base / name
        (folder / "app").mkdir(parents=True, exist_ok=True)
        failures += _check(f"archive_top accepts the single top folder {name}/", top(base) == folder)
        folder.joinpath("app").rmdir()
        folder.rmdir()
    for made, want in (((), "empty"), (("a", "b"), "more than one")):
        for name in made:
            (base / name).mkdir(parents=True, exist_ok=True)
        base.mkdir(parents=True, exist_ok=True)
        try:
            top(base)
            failures += _check(f"archive_top refuses an archive with {len(made)} top folders", False)
        except RuntimeError as exc:
            failures += _check(f"archive_top refuses an archive with {len(made)} top folders",
                               want in str(exc), f"({exc})")
        for name in made:
            (base / name).rmdir()
    return failures


def check_whats_new() -> int:
    failures = 0
    text = updater.whats_new(NOTES, "9.9.10")
    failures += _check("whats_new takes only that version's section",
                       "UPDATE waits for the old version" in text and "Run the installer" not in text,
                       f"({text!r})")
    failures += _check("whats_new is plain text (no tags, link targets or markdown)",
                       "<" not in text and "http" not in text and "**" not in text
                       and "##" not in text and "the notes" in text, f"({text!r})")
    failures += _check("whats_new accepts a v prefix", updater.whats_new(NOTES, "v9.9.10") == text)
    failures += _check("whats_new for another version is empty", updater.whats_new(NOTES, "9.9.11") == "")
    failures += _check("whats_new of no notes is empty", updater.whats_new("", "9.9.10") == "")
    long = "## What's new in 1.0.0\n" + "\n".join(f"- item {i} " + "x" * 40 for i in range(100))
    cut = updater.whats_new(long, "1.0.0")
    failures += _check("whats_new is length-limited", len(cut) <= updater.WHATS_NEW_LIMIT + 2
                       and cut.endswith("\u2026"), f"({len(cut)} chars)")
    return failures


class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def check_download() -> int:
    """sha256 checked while streaming; a bad file leaves no .part behind."""
    failures = 0
    payload = b"MZ" + os.urandom(3_000_000)
    good = "sha256:" + hashlib.sha256(payload).hexdigest()
    bad = "sha256:" + "0" * 64
    folder = Path(_TMP.name) / "SCAssistant-update"

    def run(digest, size=len(payload), cancelled=None):
        rel = _release("9.9.10", "https://x/setup", size, digest, NOTES)
        with _Patch(updater, latest_release=lambda t=15.0: rel), \
                _Patch(updater.tempfile, gettempdir=lambda: _TMP.name), \
                _Patch(updater.urllib.request, urlopen=lambda req, timeout=0: _FakeResponse(payload)):
            if cancelled is None:
                return updater.download_setup()
            return updater.download_setup(cancelled=cancelled)

    def leftovers():
        return sorted(p.name for p in folder.glob("*")) if folder.is_dir() else []

    try:
        run(bad)
        failures += _check("a digest mismatch is rejected", False)
    except RuntimeError as exc:
        failures += _check("a digest mismatch is rejected", "sha256" in str(exc), f"({exc})")
    failures += _check("and leaves no .part or Setup behind", leftovers() == [], f"({leftovers()})")

    got = run(good)
    path, version = (got.path, got.version) if hasattr(got, "path") else (got, None)
    failures += _check("a matching digest is accepted", Path(path).read_bytes() == payload)
    failures += _check("the download is saved as SCAssistant-9.9.10-Setup.exe in SCAssistant-update",
                       Path(path).name == "SCAssistant-9.9.10-Setup.exe"
                       and Path(path).parent == folder, f"({path})")
    failures += _check("download_setup returns the version it downloaded", version == "9.9.10", f"({version})")
    Path(path).unlink()

    got = run("")
    failures += _check("no digest from GitHub: size and MZ checks still pass",
                       Path(getattr(got, "path", got)).is_file())
    Path(getattr(got, "path", got)).unlink()

    try:
        run(good, size=len(payload) + 1)
        failures += _check("a short download is rejected", False)
    except RuntimeError:
        failures += _check("a short download is rejected", leftovers() == [], f"({leftovers()})")

    try:
        run(good, cancelled=lambda: True)
        failures += _check("a cancelled download stops", False)
    except Exception:
        failures += _check("a cancelled download stops and removes the .part", leftovers() == [],
                           f"({leftovers()})")
    return failures


def check_installer_command() -> int:
    """The hand-off's PowerShell: no wait limit; old version back on exit 1/2."""
    failures = 0
    calls: list = []

    class _Popen:
        def __init__(self, args, **kw):
            calls.append((args, kw))

    setup = Path(_TMP.name) / "it's here" / "SCAssistant-9.9.10-Setup.exe"
    with _Patch(updater.subprocess, Popen=_Popen):
        updater.run_installer(setup, wait_for_pid=4242)
    args, kw = calls[-1]
    command = args[-1]
    failures += _check("hand-off waits for the app with no time limit", "Wait-Process -Id 4242" in command
                       and "-Timeout" not in command, f"({command[:90]}…)")
    failures += _check("hand-off quotes the Setup path", str(setup).replace("'", "''") in command)
    failures += _check("hand-off relaunches this EXE if Setup exits 1 or 2",
                       "-eq 1" in command and "-eq 2" in command
                       and str(sys.executable).replace("'", "''") in command, f"({command[-120:]})")
    failures += _check("hand-off waits for Setup itself, not its children (no Start-Process -Wait)",
                       "-PassThru" in command and "WaitForExit" in command and " -Wait " not in command + " ")
    flags = kw.get("creationflags", 0)
    if sys.platform == "win32":
        failures += _check("hand-off keeps CREATE_NO_WINDOW + breakaway", flags == 0x08000000 | 0x01000000,
                           f"({flags:#x})")
    return failures


def check_installer_real() -> int:
    """Run the hand-off's PowerShell for real against a fake Setup.

    The fake Setup and the "old version" are pythonw with a sitecustomize that
    logs each start (and exits with the code asked for), so nothing is shown
    and nothing is installed. ~2-4 s.
    """
    if sys.platform != "win32" or not hasattr(updater, "installer_command"):
        return _check("hand-off command runs for real (installer_command)", sys.platform != "win32")
    failures = 0
    pyw = Path(sys.base_prefix) / "pythonw.exe"
    site = Path(_TMP.name) / "fake-site"
    site.mkdir(exist_ok=True)
    log = Path(_TMP.name) / "starts.log"
    (site / "sitecustomize.py").write_text(
        "import os, sys\n"
        f"with open({str(log)!r}, 'a', encoding='utf-8') as fh:\n"
        "    fh.write(' '.join(sys.orig_argv[1:]) + '\\n')\n"
        "if '/VERYSILENT' in sys.orig_argv:\n"
        "    os._exit(int(os.environ.get('CA_FAKE_SETUP_EXIT', '0')))\n", encoding="utf-8")
    gone = subprocess.Popen([sys.executable, "-c", "pass"])   # "the app", already exited
    gone.wait()
    gone_pid = gone.pid
    for code, want_relaunch in ((2, True), (1, True), (0, False)):
        log.unlink(missing_ok=True)
        command = updater.installer_command(pyw, gone_pid, str(pyw))
        env = dict(os.environ, PYTHONPATH=str(site), CA_FAKE_SETUP_EXIT=str(code))
        started = time.monotonic()
        subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
                       env=env, timeout=60, creationflags=0x08000000,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        _wait(lambda: log.is_file() and len(log.read_text().splitlines()) >= (2 if want_relaunch else 1), 5)
        lines = log.read_text().splitlines() if log.is_file() else []
        ran_setup = any("/VERYSILENT" in line for line in lines)
        relaunched = any("/VERYSILENT" not in line for line in lines)
        failures += _check(f"real hand-off, Setup exits {code}: Setup ran"
                           f"{', old version started again' if want_relaunch else ', nothing relaunched'}",
                           ran_setup and relaunched == want_relaunch,
                           f"({lines}, {time.monotonic() - started:.1f} s)")
    return failures


def check_settings_flow() -> int:
    from app.ui import settings_panel
    from app.ui.settings_panel import SettingsPanel

    failures = 0
    fake_setup = str(Path(_TMP.name) / "SCAssistant-9.9.10-Setup.exe")
    downloads: list[bool] = []

    def fake_download(t=300.0, cancelled=None):
        downloads.append(True)
        make = getattr(updater, "Downloaded", None)
        # The release moved on between CHECK (9.9.9) and UPDATE (9.9.10).
        return make(Path(fake_setup), "9.9.10") if make else Path(fake_setup)

    with _Patch(updater, is_frozen=lambda: True, standalone=lambda: False,
                newest=lambda t=15.0: (updater.VERSION, "9.9.9", True),
                check=lambda t=15.0: ("9.9.9", NOTES.replace("9.9.10", "9.9.9")),
                download_setup=fake_download):
        panel = SettingsPanel()
        asked: list[str] = []
        panel.install_requested.connect(asked.append)
        panel.update_btn.click()
        _wait(lambda: panel._update_worker is None)
        failures += _check("CHECK finds v9.9.9", panel.update_btn.text() == "UPDATE"
                           and "v9.9.9 available" in panel.update_hint.text(),
                           f"({panel.update_btn.text()!r}, {panel.update_hint.text()!r})")
        wn = getattr(panel, "whats_new_label", None)
        failures += _check("CHECK shows What's new in v9.9.9 from the release",
                           wn is not None and not wn.isHidden() and wn.text().startswith("What's new in v9.9.9")
                           and "waits for the old version" in wn.text() and "<script>" not in wn.text(),
                           f"({wn.text() if wn else None!r})")
        failures += _check("UPDATE tooltip says it installs and restarts",
                           "installer" in panel.update_btn.toolTip(), f"({panel.update_btn.toolTip()!r})")
        panel.update_btn.click()
        _wait(lambda: bool(asked) and panel._update_worker is None)
        failures += _check("UPDATE downloads the installer", downloads == [True])
        failures += _check("then asks the app to install it", asked == [fake_setup], f"({asked})")
        failures += _check("and names the version actually downloaded (9.9.10)",
                           "v9.9.10" in panel.update_hint.text() and "starts again" in panel.update_hint.text(),
                           f"({panel.update_hint.text()!r})")
        failures += _check("the button stays disabled during the hand-off", not panel.update_btn.isEnabled())
        panel.update_btn.click()
        QApplication.processEvents()
        failures += _check("a second click does nothing", downloads == [True] and asked == [fake_setup])
        fail = getattr(panel, "install_failed", None)
        if fail is not None:
            fail("powershell missing")
        failures += _check("install_failed restores UPDATE with the error",
                           fail is not None and panel.update_btn.isEnabled()
                           and panel.update_btn.text() == "UPDATE"
                           and "powershell missing" in panel.update_hint.text(),
                           f"({panel.update_btn.text()!r}, {panel.update_hint.text()!r})")
        panel.deleteLater()

    # The update thread is cleaned up, and waited for at quit.
    with _Patch(updater, is_frozen=lambda: True, standalone=lambda: False,
                check=lambda t=15.0: ("9.9.9", ""),
                newest=lambda t=15.0: (updater.VERSION, "9.9.9", True)):
        panel = SettingsPanel()
        panel.update_btn.click()
        worker = panel._update_worker
        destroyed: list[bool] = []
        worker.destroyed.connect(lambda *_: destroyed.append(True))
        _wait(lambda: panel._update_worker is None and bool(destroyed), 3)
        failures += _check("finished update thread is deleted (deleteLater)", bool(destroyed))
        wn = getattr(panel, "whats_new_label", None)
        failures += _check("no notes: no What's new box", wn is None or wn.isHidden())

        def slow_download(t=300.0, cancelled=None):
            while not (cancelled and cancelled()):
                time.sleep(0.02)
            raise RuntimeError("the download was cancelled")
        with _Patch(updater, download_setup=slow_download):
            panel.update_btn.click()
            _wait(lambda: panel._update_worker is not None and panel._update_worker.isRunning(), 2)
            running = panel._update_worker
            shut = getattr(panel, "shutdown", None)
            t0 = time.monotonic()
            ok = bool(shut and shut(3000))
            failures += _check("shutdown() cancels the download and waits for the thread",
                               ok and not running.isRunning(), f"({time.monotonic() - t0:.2f} s)")
        panel.deleteLater()

    opened: list[str] = []
    with _Patch(updater, is_frozen=lambda: True, standalone=lambda: True,
                newest=lambda t=15.0: (updater.VERSION, "9.9.9", True),
                check=lambda t=15.0: ("9.9.9", ""),
                download_setup=fake_download), \
            _Patch(settings_panel.QDesktopServices, openUrl=lambda url: opened.append(url.toString())):
        downloads.clear()
        panel = SettingsPanel()
        asked = []
        panel.install_requested.connect(asked.append)
        panel.update_btn.click()
        _wait(lambda: panel._update_worker is None)
        failures += _check("standalone: tooltip says it opens the Releases page",
                           "Releases page" in panel.update_btn.toolTip(), f"({panel.update_btn.toolTip()!r})")
        panel.update_btn.click()
        QApplication.processEvents()
        failures += _check("standalone: UPDATE opens the Releases page", opened == [updater.RELEASES_PAGE], f"({opened})")
        failures += _check("standalone: nothing downloaded or installed", not downloads and not asked)
        panel.deleteLater()
    return failures


def check_tracking_slider() -> int:
    """Whole 50-px steps; one tracking_changed per drag (on release)."""
    from app.ui.settings_panel import SettingsPanel

    failures = 0
    panel = SettingsPanel()
    emitted: list[int] = []
    panel.tracking_changed.connect(emitted.append)
    s = panel.tracking_slider
    failures += _check("tracking slider counts whole steps 0..16 (x 50 px)",
                       (s.minimum(), s.maximum(), s.singleStep()) == (0, 16, 1),
                       f"({s.minimum()}, {s.maximum()}, {s.singleStep()})")
    panel.set_tracking(400)
    failures += _check("set_tracking(400) shows ±400 px and emits nothing",
                       panel.tracking_label.text() == "±400 px" and emitted == [], f"(emitted {emitted})")
    panel.set_tracking(230)
    failures += _check("set_tracking snaps 230 to ±250 px", panel.tracking_label.text() == "±250 px")
    # A drag: the handle passes many positions, then is released.
    s.setSliderDown(True)
    for pos in (s.value() + 1, s.value() + 2, s.value() + 3, s.value() + 4, s.value() + 5):
        s.setSliderPosition(min(s.maximum(), pos))
        QApplication.processEvents()
    mid_label = panel.tracking_label.text()
    during = list(emitted)
    s.setSliderDown(False)
    QApplication.processEvents()
    failures += _check("label follows the drag", mid_label == "±500 px", f"({mid_label!r})")
    failures += _check("nothing emitted (saved) during the drag", during == [], f"(emitted {during})")
    failures += _check("one tracking_changed on release, in px", emitted == [500], f"(emitted {emitted})")
    emitted.clear()
    s.setSliderDown(True)
    s.setSliderPosition(0)
    s.setSliderDown(False)
    QApplication.processEvents()
    failures += _check("drag to 0 shows OFF and emits 0 once",
                       panel.tracking_label.text() == "OFF" and emitted == [0], f"(emitted {emitted})")
    panel.deleteLater()
    return failures


def check_setters_quiet() -> int:
    """Programmatic setters show a state; they do not report it back."""
    from app.ui.settings_panel import SettingsPanel

    failures = 0
    panel = SettingsPanel()
    seen: list[str] = []
    panel.pause_toggled.connect(lambda v: seen.append(f"pause {v}"))
    panel.debug_toggled.connect(lambda v: seen.append(f"debug {v}"))
    panel.voice_toggled.connect(lambda v: seen.append(f"voice {v}"))
    panel.tracking_changed.connect(lambda v: seen.append(f"tracking {v}"))
    panel.set_paused(True)
    panel.set_debug(True)
    panel.set_voice(False)
    panel.set_tracking(600)
    failures += _check("set_paused/set_debug/set_voice/set_tracking emit nothing", seen == [], f"({seen})")
    failures += _check("but show the state", panel.pause_btn.text() == "RESUME"
                       and not panel.preview.isHidden() and panel.voice_btn.text() == "OFF"
                       and not panel.volume_slider.isEnabled())
    panel.pause_btn.click()
    failures += _check("a user click still emits", seen == ["pause False"], f"({seen})")
    panel.deleteLater()
    return failures


def check_pin_and_attention() -> int:
    from app.ui.settings_panel import SettingsPanel

    failures = 0
    panel = SettingsPanel()
    toggled: list[bool] = []
    panel.pin_toggled.connect(toggled.append)
    panel.set_pinned(True)
    failures += _check("set_pinned(True) shows pinned, emits nothing", panel.pinned and toggled == [])
    panel.pin_btn.click()
    failures += _check("clicking the pin emits pin_toggled(False)", toggled == [False] and not panel.pinned)
    head = panel.layout().itemAt(0).layout()
    widgets = [head.itemAt(i).widget() for i in range(head.count())]
    i_pin = widgets.index(panel.pin_btn) if panel.pin_btn in widgets else -1
    failures += _check("pin sits just left of the ✕", i_pin >= 0 and i_pin + 1 < len(widgets)
                       and getattr(widgets[i_pin + 1], "text", lambda: "")() == "✕")
    base = panel.region_btn.styleSheet()
    panel.set_draw_region_attention(True)
    bright = panel.region_btn.styleSheet()
    styles = {bright}
    _wait(lambda: (styles.add(panel.region_btn.styleSheet()) or len(styles) > 1), 2)
    failures += _check("DRAW REGION attention: brighter border, pulsing",
                       panel.draw_region_attention and bright != base and len(styles) > 1)
    panel.set_draw_region_attention(False)
    failures += _check("attention off: back to the normal red", not panel.draw_region_attention
                       and panel.region_btn.styleSheet() == base)
    panel.deleteLater()
    return failures


def check_app_handoff() -> int:
    """OverlayApp runs the hand-off, then quits; a failed hand-off does not quit."""
    from app.config import Config
    from app.main import OverlayApp

    failures = 0
    app = QApplication.instance()
    overlay = OverlayApp(app, Config())
    calls: list[tuple] = []
    quits: list[bool] = []
    overlay.quit = lambda: quits.append(True)
    with _Patch(updater, run_installer=lambda setup, wait_for_pid=None, relaunch=None: calls.append((str(setup), wait_for_pid))):
        overlay.settings.install_requested.emit("C:/x/SCAssistant-9.9.9-Setup.exe")
        failures += _check("app starts the hand-off for that Setup", calls == [(str(Path("C:/x/SCAssistant-9.9.9-Setup.exe")), None)],
                           f"({calls})")
        failures += _check("then quits so Setup can run", quits == [True])

    def broken(setup, wait_for_pid=None, relaunch=None):
        raise OSError("powershell missing")
    quits.clear()
    with _Patch(updater, run_installer=broken):
        overlay.settings.install_requested.emit("C:/x/SCAssistant-9.9.9-Setup.exe")
        failures += _check("a failed hand-off does not quit", quits == [])
        failures += _check("and says why", "powershell missing" in overlay.settings.update_hint.text(),
                           f"({overlay.settings.update_hint.text()!r})")
    overlay.scan.stop()
    overlay.scan.wait(1500)
    return failures


def check_live_release() -> int:
    try:
        release = updater.latest_release()
        version, url, size = release[0], release[1], release[2]
    except Exception as exc:  # network
        return _check("latest release readable on GitHub", False, f"({exc})")
    digest = getattr(release, "digest", "")
    return _check("latest release on GitHub has an installer",
                  url.endswith(version.SETUP_ASSET.format(version=version)) and size > 10_000_000,
                  f"(v{version}, {size // 1_000_000} MB, digest {'yes' if digest else 'no'}, {url})")


def _run(fn) -> int:
    try:
        return fn()
    except Exception:
        print(f"  FAIL  {fn.__name__} raised:")
        traceback.print_exc(limit=3, file=sys.stdout)
        return 1


def main() -> int:
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    if QApplication.instance() is None:
        QApplication(sys.argv)
    failures = 0
    checks = [check_names, check_release_parsing, check_whats_new, check_download, check_installer_command,
              check_installer_real, check_settings_flow, check_tracking_slider,
              check_setters_quiet, check_pin_and_attention, check_app_handoff]
    if "--offline" not in sys.argv:
        checks.append(check_live_release)
    for fn in checks:
        failures += _run(fn)
        print("-" * 78)
    print("ALL CHECKS PASSED" if failures == 0 else f"{failures} CHECK(S) FAILED")
    return failures


if __name__ == "__main__":
    raise SystemExit(main())
