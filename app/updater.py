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
* ``%APPDATA%\\SC Assistant`` is never touched — settings, notes and logs
  live there, not in the install folder.

The installed EXE (SCAssistant-X.Y.Z-Setup.exe) updates through the
installer instead: Windows will not let a running .exe replace its own files.
CHECK reads the latest GitHub *release* (not ``main``, which can be ahead of
what is released), UPDATE downloads that release's Setup.exe, and
``run_installer`` starts it silently once this process has exited — Setup
refuses while SC Assistant runs (AppMutex) — with ``/LAUNCH=1`` so the
new version starts by itself (and the old one again if Setup stops without
installing). The download is checked against GitHub's sha256 digest, and
``whats_new`` turns the release notes into plain text for Settings. A standalone (zip) EXE is not registered as
installed, so it is not updated in place: ``standalone()`` reports that case.
"""
from __future__ import annotations

import hashlib
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
from typing import Callable, NamedTuple

from . import version as _names
from .version import VERSION

# This fork; the names live in app/version.py. Upstream
# (fishtaco7/citizen-assistant) does not have its fixes, so updating from
# there would undo them.
REPO = _names.REPO
BRANCH = "main"
RAW_VERSION = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/app/version.py"
ARCHIVE = f"https://codeload.github.com/{REPO}/zip/refs/heads/{BRANCH}"
USER_AGENT = _names.USER_AGENT
LATEST_RELEASE = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases"
# The release's Setup.exe (e.g. SCAssistant-1.0.1-Setup.exe), never a TEST
# edition; built from version.SETUP_ASSET so the two cannot drift apart.
_SETUP_HEAD, _SETUP_TAIL = _names.SETUP_ASSET.split("{version}")
SETUP_ASSET = re.compile("^" + re.escape(_SETUP_HEAD) + r"(\d+\.\d+\.\d+)"
                         + re.escape(_SETUP_TAIL) + "$")
# The installer's uninstall entry (installer/sc_assistant.iss AppId, the same
# GUID as before the rename, so updates still find the install).
INSTALL_KEY = (r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
               r"\{C4736091-9D04-4E7B-B53D-4FA025CCB796}_is1")

COPY_DIRS = ("app", "tools")
COPY_FILES = (
    "launcher.py",
    "sc-assistant.spec",
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
        published = latest_release(timeout).version
    else:
        published = published_version(timeout)
    return VERSION, published, _newer(published, VERSION)


# -- installed EXE: update through the release's Setup.exe ------------------
class Release(NamedTuple):
    """A release's Setup.exe and its notes."""

    version: str
    url: str
    size: int
    digest: str      # GitHub's "sha256:<hex>", "" when the API gives none
    body: str        # release text (markdown), "" when empty


def setup_asset(release: dict) -> Release | None:
    """The Setup.exe of a GitHub release (API JSON), or None."""
    for asset in release.get("assets") or []:
        match = SETUP_ASSET.match(str(asset.get("name", "")))
        if match:
            return Release(match.group(1), str(asset.get("browser_download_url", "")),
                           int(asset.get("size") or 0), str(asset.get("digest") or ""),
                           str(release.get("body") or ""))
    return None


def latest_release(timeout: float = 15.0) -> Release:
    """The fork's latest GitHub release (its Setup.exe and notes)."""
    body = _text_at(LATEST_RELEASE, timeout)
    try:
        release = json.loads(body)
    except ValueError as exc:
        raise RuntimeError("GitHub returned an unexpected release list") from exc
    found = setup_asset(release)
    if found is None or not found.url:
        raise RuntimeError(f"release {release.get('tag_name', '?')} has no installer")
    return found


def check(timeout: float = 15.0) -> tuple[str, str]:
    """(published version, release notes) for CHECK.

    Same source as ``newest``; the notes come from the latest release, and a
    source install only gets them when that release is the version on main.
    """
    if is_frozen():
        release = latest_release(timeout)
        return release.version, release.body
    published = published_version(timeout)
    try:
        release = latest_release(timeout)
    except Exception:            # notes are a nicety; the version is what counts
        return published, ""
    return published, (release.body if release.version == published else "")


WHATS_NEW_LIMIT = 700
_HEADING = re.compile(r"^##\s+what['\u2019]s\s+new\s+in\s+v?(\S+)\s*$", re.IGNORECASE)


def whats_new(body: str, version: str, limit: int = WHATS_NEW_LIMIT) -> str:
    """Plain text of the "## What's new in <version>" section of release notes.

    Stops at the next "## " heading. Markup is removed (HTML tags, links,
    emphasis) so the text can only ever be shown as text; longer than
    ``limit`` characters it is cut at a line and ends with "…".
    """
    want = str(version or "").strip().lstrip("vV")
    lines = str(body or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    taken: list[str] = []
    inside = False
    for line in lines:
        if line.startswith("## "):
            if inside:
                break
            match = _HEADING.match(line.strip())
            inside = bool(match and want and match.group(1).lstrip("vV") == want)
            continue
        if inside:
            taken.append(line)
    out: list[str] = []
    for line in taken:
        text = re.sub(r"<[^>]*>", "", line)                       # HTML tags
        text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)    # [text](url)
        text = re.sub(r"(\*\*|__|`)", "", text)
        text = text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
        text = text.rstrip()
        heading = re.match(r"^#{3,6}\s+(.*)$", text)
        if heading:
            text = heading.group(1).strip() + ":"
        bullet = re.match(r"^(\s*)[-*+]\s+(.*)$", text)
        if bullet:
            text = f"{bullet.group(1)}\u2022 {bullet.group(2)}"
        if text or (out and out[-1]):
            out.append(text)
    plain = "\n".join(out).strip()
    if len(plain) > limit:
        cut = plain[:limit]
        cut = cut[:cut.rfind("\n")] if "\n" in cut else cut
        plain = cut.rstrip() + "\n\u2026"
    return plain


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


class Downloaded(NamedTuple):
    path: Path
    version: str     # the version actually downloaded (the release at the time)


def download_setup(timeout: float = 300.0,
                   cancelled: Callable[[], bool] | None = None) -> Downloaded:
    """Download the latest release's Setup.exe to a temporary folder.

    The file is checked against the release's size, the EXE header and, when
    GitHub gives one, its sha256 digest; anything wrong (or ``cancelled()``
    turning true) removes the partial file and raises.
    """
    release = latest_release(min(timeout, 30.0))
    target = (Path(tempfile.gettempdir()) / f"{_names.EXE_NAME}-update"
              / _names.SETUP_ASSET.format(version=release.version))
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(".part")
    algo, _, want = release.digest.partition(":")
    hasher = hashlib.sha256() if algo.strip().lower() == "sha256" and want else None
    try:
        request = urllib.request.Request(release.url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=timeout) as response, \
                open(partial, "wb") as out:
            while True:
                if cancelled is not None and cancelled():
                    raise RuntimeError("the download was cancelled")
                chunk = response.read(1 << 20)
                if not chunk:
                    break
                out.write(chunk)
                if hasher is not None:
                    hasher.update(chunk)
        got = partial.stat().st_size
        with open(partial, "rb") as fh:
            is_exe = fh.read(2) == b"MZ"
        if (release.size and got != release.size) or not is_exe:
            raise RuntimeError(
                f"the installer download is incomplete ({got} of {release.size} bytes)")
        if hasher is not None and hasher.hexdigest().lower() != want.strip().lower():
            raise RuntimeError("the installer download is damaged (sha256 does not match)")
        partial.replace(target)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    return Downloaded(target, release.version)


def _ps_quote(text) -> str:
    """A PowerShell single-quoted string literal."""
    return "'" + str(text).replace("'", "''") + "'"


def installer_command(setup: Path, pid: int, relaunch: str | None) -> str:
    """The PowerShell the hand-off runs (separate so tests can read it).

    Waits for ``pid`` with no time limit (a slow exit would otherwise start
    Setup while the app still holds its AppMutex), runs Setup and waits for
    Setup itself: ``$p.WaitForExit()``, not ``Start-Process -Wait``, which
    also waits for every child process, i.e. for the new version Setup starts
    (/LAUNCH=1). Exit 1 (Setup could not start) or 2 (it stopped before
    installing) starts ``relaunch``, the old version, again.
    """
    command = (
        f"Wait-Process -Id {int(pid)} -ErrorAction SilentlyContinue; "
        "$code = 1; "
        f"try {{ $p = Start-Process -FilePath {_ps_quote(setup)} -ArgumentList "
        "'/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/LAUNCH=1' -PassThru; "
        "$null = $p.Handle; $p.WaitForExit(); $code = $p.ExitCode } catch { $code = 1 }"
    )
    if relaunch:
        command += (f"; if ($code -eq 1 -or $code -eq 2) "
                    f"{{ Start-Process -FilePath {_ps_quote(relaunch)} }}")
    return command


def run_installer(setup: Path, wait_for_pid: int | None = None,
                  relaunch: str | None = None) -> None:
    """Run ``setup`` silently once process ``wait_for_pid`` (default: this one)
    has exited, then let it start the new version (``/LAUNCH=1``).

    Setup refuses to run while SC Assistant is open, so a hidden
    PowerShell waits for the exit first; the caller quits right after this.
    If Setup stops without installing (exit 1 or 2), ``relaunch`` (default:
    this EXE, ``sys.executable``) is started again.
    """
    pid = os.getpid() if wait_for_pid is None else int(wait_for_pid)
    command = installer_command(setup, pid,
                                sys.executable if relaunch is None else relaunch)
    args = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-WindowStyle", "Hidden", "-Command", command]
    # CREATE_NO_WINDOW, not DETACHED_PROCESS: PowerShell started with no
    # console at all never runs its command (tested: the detached helper did
    # nothing, every CREATE_NO_WINDOW one ran and outlived its parent).
    # CREATE_BREAKAWAY_FROM_JOB first, as restart() does, so a launcher that
    # runs us in a job object cannot kill the helper when we quit; jobs that
    # refuse breakaway get the plain retry.
    attempts = [0x08000000 | 0x01000000, 0x08000000] if sys.platform == "win32" else [0]
    for i, flags in enumerate(attempts):
        try:
            subprocess.Popen(args, creationflags=flags, close_fds=True,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
            return
        except OSError:
            if i == len(attempts) - 1:
                raise


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


def archive_top(folder: Path) -> Path:
    """The one top folder of an unpacked branch archive.

    GitHub wraps the tree in "<repo>-<branch>/" (now "sc-assistant-main/"),
    so the name follows the repository's and is not checked.
    """
    tops = [path for path in folder.iterdir() if path.is_dir()]
    if not tops:
        raise RuntimeError("the update archive was empty")
    if len(tops) > 1:
        raise RuntimeError("the update archive has more than one top folder")
    return tops[0]


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
    with tempfile.TemporaryDirectory(prefix="sca-update-") as tmp:
        with zipfile.ZipFile(io.BytesIO(blob)) as bundle:
            bundle.extractall(tmp)
        source = archive_top(Path(tmp))
        version = _version_in(source)
        _copy_tree(source, root)
    return version
