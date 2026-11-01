"""Update this install from the public GitHub repository.

The overlay is a folder of Python files, so updating means replacing those
files and restarting the process: there is nothing to install and no registry
entry to rewrite.  The work is deliberately conservative:

* the archive is fetched over HTTPS and unpacked into a temporary folder first,
  so a failed download cannot leave a half-written install;
* only files that ship with the app are copied (``app/``, ``tools/``, the
  launchers, the spec, requirements, README);
* ``opencode.jsonc`` is never touched — it holds this project's agent
  permissions, which belong to the user, not to the project;
* ``%APPDATA%\\Citizen Assistant`` is never touched — settings, notes and logs
  live there, not in the install folder.

The installed EXE (CitizenAssistant-X.Y.Z-Setup.exe) updates through the
installer instead: Windows will not let a running .exe replace its own files.
CHECK reads the latest GitHub *release* (not ``main``, which can be ahead of
what is released), UPDATE downloads that release's Setup.exe, and
``run_installer`` starts it silently once this process has exited — Setup
refuses while Citizen Assistant runs (AppMutex) — with ``/LAUNCH=1`` so the
new version starts by itself. A standalone (zip) EXE is not registered as
installed, so it is not updated in place: ``standalone()`` reports that case.
"""
from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

from .version import VERSION

# This fork. Upstream (fishtaco7/citizen-assistant) does not have its fixes,
# so updating from there would undo them; see CHANGES.md v1.2.17.
REPO = "swill008/citizen-assistant"
BRANCH = "main"
RAW_VERSION = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/app/version.py"
ARCHIVE = f"https://codeload.github.com/{REPO}/zip/refs/heads/{BRANCH}"
USER_AGENT = (f"Citizen-Assistant/{VERSION} "
              "(+https://github.com/swill008/citizen-assistant)")
LATEST_RELEASE = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases"
SETUP_ASSET = re.compile(r"^CitizenAssistant-(\d+\.\d+\.\d+)-Setup\.exe$")
# The installer's uninstall entry (installer/citizen_assistant.iss AppId).
INSTALL_KEY = (r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
               r"\{C4736091-9D04-4E7B-B53D-4FA025CCB796}_is1")

COPY_DIRS = ("app", "tools")
COPY_FILES = (
    "launcher.py",
    "citizen-assistant.spec",
    "requirements.txt",
    "requirements-lock.txt",
    "install.bat",
    "uninstall.bat",
    "setup.bat",
    "run.bat",
    "run-debug.bat",
    "run.command",
    "run-hidden.vbs",
    "README.md",
    "CHANGES.md",
    "LICENSE",
    "app.ico",
    ".gitignore",
)

# Never copied, even inside an otherwise-wanted folder.
SKIP_NAMES = {"__pycache__", ".git", ".venv", "opencode.jsonc"}


def is_frozen() -> bool:
    """True for the PyInstaller EXE, which cannot replace itself."""
    return bool(getattr(sys, "frozen", False))


def install_root() -> Path:
    """The folder a shortcut should point at."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def _version_tuple(text: str) -> tuple[int, ...]:
    numbers = re.findall(r"\d+", str(text or ""))
    return tuple(int(part) for part in numbers[:3]) or (0,)


def _newer(published: str, installed: str) -> bool:
    return _version_tuple(published) > _version_tuple(installed)


def _text_at(url: str, timeout: float) -> str:
    request = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    })
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", "replace")


def published_version(timeout: float = 15.0) -> str:
    """VERSION from GitHub's copy of app/version.py.

    raw.githubusercontent.com is fronted by a CDN that keeps serving the copy
    it already has for a few minutes after a push, which made CHECK report
    "up to date" right after a release. A unique query string gives the CDN a
    cache key it has never seen, so the request reaches the repository.
    """
    body = _text_at(f"{RAW_VERSION}?t={int(time.time())}", timeout)
    match = re.search(r'VERSION\s*=\s*["\']([^"\']+)', body)
    if not match:
        raise RuntimeError("GitHub returned an unexpected version file")
    return match.group(1).strip()


def newest(timeout: float = 15.0) -> tuple[str, str, bool]:
    """(installed, published, update_available).

    The EXE compares with the latest release (what an installer exists for);
    the source install with ``main``'s app/version.py.
    """
    if is_frozen():
        published = latest_release(timeout)[0]
    else:
        published = published_version(timeout)
    return VERSION, published, _newer(published, VERSION)


# -- installed EXE: update through the release's Setup.exe ------------------
def setup_asset(release: dict) -> tuple[str, str, int] | None:
    """(version, download URL, size) of a release's Setup.exe, or None."""
    for asset in release.get("assets") or []:
        match = SETUP_ASSET.match(str(asset.get("name", "")))
        if match:
            return (match.group(1), str(asset.get("browser_download_url", "")),
                    int(asset.get("size") or 0))
    return None


def latest_release(timeout: float = 15.0) -> tuple[str, str, int]:
    """(version, Setup.exe URL, size) of the fork's latest GitHub release."""
    body = _text_at(LATEST_RELEASE, timeout)
    try:
        release = json.loads(body)
    except ValueError as exc:
        raise RuntimeError("GitHub returned an unexpected release list") from exc
    found = setup_asset(release)
    if found is None or not found[1]:
        raise RuntimeError(f"release {release.get('tag_name', '?')} has no installer")
    return found


def _install_location() -> Path | None:
    """Folder the installer put the app in (its uninstall entry), or None."""
    if sys.platform != "win32":
        return None
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, INSTALL_KEY) as key:
            value, _kind = winreg.QueryValueEx(key, "InstallLocation")
    except OSError:
        return None
    return Path(str(value)) if value else None


def standalone() -> bool:
    """True for an EXE that was unzipped rather than installed by Setup.

    Running Setup would install a second copy elsewhere, so such a copy is
    updated by downloading the new zip instead.
    """
    if not is_frozen():
        return False
    where = _install_location()
    try:
        return where is None or where.resolve() != install_root().resolve()
    except OSError:
        return True


def download_setup(timeout: float = 300.0) -> Path:
    """Download the latest release's Setup.exe to a temporary folder."""
    version, url, size = latest_release(min(timeout, 30.0))
    target = Path(tempfile.gettempdir()) / "CitizenAssistant-update" / f"CitizenAssistant-{version}-Setup.exe"
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(".part")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response, open(partial, "wb") as out:
        shutil.copyfileobj(response, out, 1 << 20)
    got = partial.stat().st_size
    with open(partial, "rb") as fh:
        is_exe = fh.read(2) == b"MZ"
    if (size and got != size) or not is_exe:
        partial.unlink(missing_ok=True)
        raise RuntimeError(f"the installer download is incomplete ({got} of {size} bytes)")
    partial.replace(target)
    return target


def run_installer(setup: Path, wait_for_pid: int | None = None) -> None:
    """Run ``setup`` silently once process ``wait_for_pid`` (default: this one)
    has exited, then let it start the new version (``/LAUNCH=1``).

    Setup refuses to run while Citizen Assistant is open, so a hidden
    PowerShell waits for the exit first; the caller quits right after this.
    """
    pid = os.getpid() if wait_for_pid is None else int(wait_for_pid)
    quoted = str(setup).replace("'", "''")
    command = (
        f"Wait-Process -Id {pid} -Timeout 60 -ErrorAction SilentlyContinue; "
        f"Start-Process -FilePath '{quoted}' -ArgumentList "
        "'/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/LAUNCH=1'"
    )
    flags = 0
    if sys.platform == "win32":
        # DETACHED_PROCESS | CREATE_NO_WINDOW: no console, and it outlives us.
        flags = 0x00000008 | 0x08000000
    subprocess.Popen(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-WindowStyle", "Hidden", "-Command", command],
        creationflags=flags, close_fds=True,
    )


def is_newer(published: str) -> bool:
    """Whether ``published`` (a version string) is ahead of this install."""
    return _newer(published, VERSION)


def _version_in(folder: Path) -> str:
    path = folder / "app" / "version.py"
    try:
        body = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "?"
    match = re.search(r'VERSION\s*=\s*["\']([^"\']+)', body)
    return match.group(1).strip() if match else "?"


def _copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def _copy_tree(source: Path, root: Path) -> None:
    for name in COPY_DIRS:
        folder = source / name
        if not folder.is_dir():
            raise RuntimeError(f"the update is missing {name}/")
        for path in folder.rglob("*"):
            if not path.is_file():
                continue
            if any(part in SKIP_NAMES for part in path.relative_to(source).parts):
                continue
            _copy(path, root / path.relative_to(source))

    for name in COPY_FILES:
        path = source / name
        if path.is_file():
            _copy(path, root / name)


def apply(timeout: float = 90.0) -> str:
    """Download the branch archive and copy it over this install.

    Returns the version that was installed.  The process keeps running the old
    code until it restarts; the caller is expected to relaunch.
    """
    if is_frozen():
        raise RuntimeError("the EXE build has to be replaced by hand")

    request = urllib.request.Request(ARCHIVE, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        blob = response.read()
    if not blob:
        raise RuntimeError("GitHub sent an empty archive")

    root = install_root()
    with tempfile.TemporaryDirectory(prefix="ca-update-") as tmp:
        with zipfile.ZipFile(io.BytesIO(blob)) as bundle:
            bundle.extractall(tmp)
        # GitHub wraps the tree in a single "citizen-assistant-main/" folder.
        source = next((path for path in Path(tmp).iterdir() if path.is_dir()), None)
        if source is None:
            raise RuntimeError("the update archive was empty")
        version = _version_in(source)
        _copy_tree(source, root)
    return version
