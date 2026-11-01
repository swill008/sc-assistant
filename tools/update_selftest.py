"""UPDATE button: release lookup, the installed-EXE flow, standalone copies.

    python -m tools.update_selftest

Uses fakes for everything that would download or install, plus one live,
read-only request for the fork's latest release. The real hand-off (Setup run
after the program quits, new version started) is checked by
installer\\test_installer.ps1 -NewerSetup.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_TMP = tempfile.TemporaryDirectory(prefix="ca-update-")
os.environ["APPDATA"] = _TMP.name          # before app.config is imported

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app import updater  # noqa: E402


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


def check_release_parsing() -> int:
    failures = 0
    release = {"tag_name": "v1.2.20", "assets": [
        {"name": "CitizenAssistant-windows-x64.zip", "browser_download_url": "https://x/zip", "size": 1},
        {"name": "CitizenAssistant-1.2.20-TEST-Setup.exe", "browser_download_url": "https://x/test", "size": 2},
        {"name": "CitizenAssistant-1.2.20-Setup.exe", "browser_download_url": "https://x/setup", "size": 3},
    ]}
    failures += _check("picks the release's Setup.exe (not the zip or a TEST edition)",
                       updater.setup_asset(release) == ("1.2.20", "https://x/setup", 3),
                       f"({updater.setup_asset(release)})")
    failures += _check("no installer in a release -> None",
                       updater.setup_asset({"assets": [release["assets"][0]]}) is None)
    with _Patch(updater, is_frozen=lambda: True, latest_release=lambda t=15.0: ("9.9.9", "u", 1),
                published_version=lambda t=15.0: "0.0.1"):
        failures += _check("installed EXE: CHECK uses the latest release", updater.newest()[1:] == ("9.9.9", True))
    with _Patch(updater, is_frozen=lambda: False, latest_release=lambda t=15.0: ("9.9.9", "u", 1),
                published_version=lambda t=15.0: "0.0.1"):
        failures += _check("source install: CHECK still uses main's version.py", updater.newest()[1] == "0.0.1")
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


def check_settings_flow() -> int:
    from app.ui import settings_panel
    from app.ui.settings_panel import SettingsPanel

    failures = 0
    fake_setup = str(Path(_TMP.name) / "CitizenAssistant-9.9.9-Setup.exe")
    downloads: list[bool] = []
    with _Patch(updater, is_frozen=lambda: True, standalone=lambda: False,
                newest=lambda t=15.0: (updater.VERSION, "9.9.9", True),
                download_setup=lambda t=300.0: downloads.append(True) or Path(fake_setup)):
        panel = SettingsPanel()
        asked: list[str] = []
        panel.install_requested.connect(asked.append)
        panel.update_btn.click()
        _wait(lambda: panel._update_worker is None)
        failures += _check("CHECK finds v9.9.9", panel.update_btn.text() == "UPDATE" and "9.9.9" in panel.update_hint.text(),
                           f"({panel.update_btn.text()!r}, {panel.update_hint.text()!r})")
        panel.update_btn.click()
        _wait(lambda: bool(asked))
        failures += _check("UPDATE downloads the installer", downloads == [True])
        failures += _check("then asks the app to install it", asked == [fake_setup], f"({asked})")
        failures += _check("and says it will restart by itself", "starts again" in panel.update_hint.text(),
                           f"({panel.update_hint.text()!r})")
        panel.deleteLater()

    opened: list[str] = []
    with _Patch(updater, is_frozen=lambda: True, standalone=lambda: True,
                newest=lambda t=15.0: (updater.VERSION, "9.9.9", True),
                download_setup=lambda t=300.0: downloads.append(True) or Path(fake_setup)), \
            _Patch(settings_panel.QDesktopServices, openUrl=lambda url: opened.append(url.toString())):
        downloads.clear()
        panel = SettingsPanel()
        asked = []
        panel.install_requested.connect(asked.append)
        panel.update_btn.click()
        _wait(lambda: panel._update_worker is None)
        panel.update_btn.click()
        QApplication.processEvents()
        failures += _check("standalone: UPDATE opens the Releases page", opened == [updater.RELEASES_PAGE], f"({opened})")
        failures += _check("standalone: nothing downloaded or installed", not downloads and not asked)
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
    with _Patch(updater, run_installer=lambda setup, wait_for_pid=None: calls.append((str(setup), wait_for_pid))):
        overlay.settings.install_requested.emit("C:/x/CitizenAssistant-9.9.9-Setup.exe")
        failures += _check("app starts the hand-off for that Setup", calls == [(str(Path("C:/x/CitizenAssistant-9.9.9-Setup.exe")), None)],
                           f"({calls})")
        failures += _check("then quits so Setup can run", quits == [True])

    def broken(setup, wait_for_pid=None):
        raise OSError("powershell missing")
    quits.clear()
    with _Patch(updater, run_installer=broken):
        overlay.settings.install_requested.emit("C:/x/CitizenAssistant-9.9.9-Setup.exe")
        failures += _check("a failed hand-off does not quit", quits == [])
        failures += _check("and says why", "powershell missing" in overlay.settings.update_hint.text(),
                           f"({overlay.settings.update_hint.text()!r})")
    overlay.scan.stop()
    overlay.scan.wait(1500)
    return failures


def check_live_release() -> int:
    try:
        version, url, size = updater.latest_release()
    except Exception as exc:  # network
        return _check("latest release readable on GitHub", False, f"({exc})")
    return _check("latest release on GitHub has an installer",
                  url.endswith(f"CitizenAssistant-{version}-Setup.exe") and size > 10_000_000,
                  f"(v{version}, {size // 1_000_000} MB, {url})")


def main() -> int:
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    if QApplication.instance() is None:
        QApplication(sys.argv)
    failures = check_release_parsing()
    print("-" * 78)
    failures += check_settings_flow()
    print("-" * 78)
    failures += check_app_handoff()
    print("-" * 78)
    failures += check_live_release()
    print("-" * 78)
    print("ALL CHECKS PASSED" if failures == 0 else f"{failures} CHECK(S) FAILED")
    return failures


if __name__ == "__main__":
    raise SystemExit(main())
