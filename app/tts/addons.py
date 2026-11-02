"""Optional speech add-ons (Piper, Kokoro), downloaded on demand.

Piper and Kokoro's phonemizer/espeak-ng are GPL-3.0, so they are never bundled
into the MIT EXE: the VOICE menu downloads them from PyPI when the user picks
them. Every file is pinned by exact name and sha256; a file whose hash does not
match is deleted and refused.

Layout under ``%LOCALAPPDATA%\\SC Assistant\\voices``::

    <engine>\\lib\\        the extracted wheels (put on sys.path only when used)
    <engine>\\voices\\     the voice files from Hugging Face
    <engine>\\download\\   partial downloads (``*.part``), removed when done

Nothing here imports an add-on; ``activate`` only adds its folder to the end
of ``sys.path``, so the app's own numpy/onnxruntime always win.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import sys
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from app.tts import base

log = logging.getLogger(__name__)

CHUNK = 256 * 1024
TIMEOUT = 30.0
USER_AGENT = "SC-Assistant-voice-addons"
MARKER = ".installed.json"


class AddonError(base.EngineError):
    """An add-on could not be downloaded, checked or installed."""


@dataclass(frozen=True)
class Wheel:
    """One pinned PyPI wheel."""

    project: str
    version: str
    filename: str
    size: int
    sha256: str


@dataclass(frozen=True)
class RemoteFile:
    """One pinned file at a fixed URL (a voice or model on Hugging Face)."""

    url: str
    name: str           # file name inside the engine's voices folder
    size: int
    sha256: str


# Pinned from PyPI (the research downloads, 2026-11-01). numpy and onnxruntime
# are not here: the app already ships them.
WHEELS: dict[str, tuple[Wheel, ...]] = {
    "piper": (
        Wheel("piper-tts", "1.8.0", "piper_tts-1.8.0-cp39-abi3-win_amd64.whl", 34119688,
              "5da9bfdb05dfe15da3536859d422e605483ffa6d2b3ec2c5b9593bae6b5aa6a4"),
        Wheel("pathvalidate", "3.3.1", "pathvalidate-3.3.1-py3-none-any.whl", 24305,
              "5263baab691f8e1af96092fa5137ee17df5bdfbd6cff1fcac4d6ef4bc2e1735f"),
    ),
    "kokoro": (
        Wheel("kokoro-onnx", "0.6.1", "kokoro_onnx-0.6.1-py3-none-any.whl", 26084,
              "50c8de4950d601df41428ee5462a48c8a78bef441bf671f2492e070ef44d8a32"),
        Wheel("phonemizer", "3.4.0", "phonemizer-3.4.0-py3-none-any.whl", 108529,
              "5ff1215d0efa3606dd1b92449f6d71b5c1741efcc84c6d40c17bfaf64f6ded5f"),
        Wheel("espeakng-loader", "0.2.4", "espeakng_loader-0.2.4-py3-none-win_amd64.whl", 9437292,
              "41f1e08ac9deda2efd1ea9de0b81dab9f5ae3c4b24284f76533d0a7b1dd7abd7"),
        Wheel("joblib", "1.6.0", "joblib-1.6.0-py3-none-any.whl", 306115,
              "3dbbf9f6e4b592a2357b854608e980fe6390d131d7a82f011a377ef2ebef7aba"),
        Wheel("cloudpickle", "3.1.2", "cloudpickle-3.1.2-py3-none-any.whl", 22228,
              "9acb47f6afd73f60dc1df93bb801b472f05ff42fa6c84167d25cb206be1fbf4a"),
        Wheel("attrs", "26.1.0", "attrs-26.1.0-py3-none-any.whl", 67548,
              "c647aa4a12dfbad9333ca4e71fe62ddc36f4e63b2d260a37a8b83d2f043ac309"),
        Wheel("dlinfo", "2.0.0", "dlinfo-2.0.0-py3-none-any.whl", 3654,
              "b32cc18e3ea67c0ca9ca409e5b41eed863bd1363dbc9dd3de90fedf11b61e7bc"),
        Wheel("typing-extensions", "4.16.0", "typing_extensions-4.16.0-py3-none-any.whl", 45571,
              "481caa481374e813c1b176ada14e97f1f67a4539ce9cfeb3f350d78d6370c2e8"),
    ),
}

# Parts of a wheel the app never uses (Piper's Hebrew model, training code,
# HTTP server): not extracted, which saves ~22 MB on disk.
SKIP_PREFIXES: dict[str, tuple[str, ...]] = {
    "piper": ("piper/hebrew/", "piper/train/", "piper/templates/", "piper/img/"),
}


# ---- folders ----------------------------------------------------------------
def addon_dir() -> Path:
    """``%LOCALAPPDATA%\\SC Assistant\\voices`` (read now, so tests can redirect it)."""
    root = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(root) / "SC Assistant" / "voices"


ADDON_DIR = addon_dir()


def engine_dir(engine: str) -> Path:
    return addon_dir() / engine


def lib_dir(engine: str) -> Path:
    return engine_dir(engine) / "lib"


def voices_dir(engine: str) -> Path:
    return engine_dir(engine) / "voices"


def _download_dir(engine: str) -> Path:
    return engine_dir(engine) / "download"


# ---- network ----------------------------------------------------------------
def _open(url: str, timeout: float = TIMEOUT) -> BinaryIO:
    """Open ``url`` for reading (replaced by the self-test to serve local files)."""
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    return urllib.request.urlopen(req, timeout=timeout)   # noqa: S310 - fixed https hosts


def wheel_url(wheel: Wheel) -> str:
    """The download URL PyPI gives for ``wheel``, after checking its sha256 there."""
    url = f"https://pypi.org/pypi/{wheel.project}/{wheel.version}/json"
    try:
        with _open(url) as resp:
            meta = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:        # noqa: BLE001 - no network, PyPI down
        raise AddonError(f"PyPI: {wheel.project} {wheel.version}: {exc}") from exc
    for entry in meta.get("urls", ()):
        if entry.get("filename") == wheel.filename:
            if (entry.get("digests") or {}).get("sha256", "").lower() != wheel.sha256:
                raise AddonError(f"PyPI lists a different sha256 for {wheel.filename}; refused")
            return str(entry["url"])
    raise AddonError(f"PyPI has no {wheel.filename}")


Progress = Callable[[int, int], None]
CancelCheck = Callable[[], bool]


def fetch(url: str, dest: Path, sha256: str, size: int = 0, *,
          progress: Progress | None = None, cancelled: CancelCheck | None = None,
          done_before: int = 0, total: int = 0) -> Path:
    """Download ``url`` to ``dest``, checking its sha256.

    ``progress(got, total)`` counts from ``done_before`` so several files show
    as one bar. A wrong hash or size deletes the file and raises AddonError;
    ``cancelled()`` deletes it and raises base.Cancelled.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    hasher = hashlib.sha256()
    got = 0
    total = total or size
    try:
        with _open(url) as resp, open(part, "wb") as out:
            while True:
                if cancelled is not None and cancelled():
                    raise base.Cancelled()
                block = resp.read(CHUNK)
                if not block:
                    break
                out.write(block)
                hasher.update(block)
                got += len(block)
                if size and got > size:
                    raise AddonError(f"{dest.name}: larger than the pinned {size} bytes; refused")
                if progress is not None:
                    progress(done_before + got, total)
    except (base.Cancelled, AddonError):
        part.unlink(missing_ok=True)
        raise
    except Exception as exc:        # noqa: BLE001 - network or disk
        part.unlink(missing_ok=True)
        raise AddonError(f"{dest.name}: download failed: {exc}") from exc
    if hasher.hexdigest() != sha256.lower() or (size and got != size):
        part.unlink(missing_ok=True)
        raise AddonError(f"{dest.name}: sha256 does not match the pinned value; refused")
    os.replace(part, dest)
    return dest


def file_ok(path: Path, sha256: str, size: int = 0) -> bool:
    """``path`` exists with the pinned size and sha256."""
    try:
        if size and path.stat().st_size != size:
            return False
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for block in iter(lambda: f.read(CHUNK), b""):
                h.update(block)
    except OSError:
        return False
    return h.hexdigest() == sha256.lower()


# ---- engine packages --------------------------------------------------------
def _pins(engine: str) -> list[str]:
    return [w.sha256 for w in WHEELS[engine]]


def installed(engine: str) -> bool:
    """The engine's pinned wheels are extracted (the marker lists their hashes)."""
    try:
        data = json.loads((lib_dir(engine) / MARKER).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and data.get("sha256") == _pins(engine)


def package_bytes(engine: str) -> int:
    """Download size of the engine package (0 when installed)."""
    return 0 if installed(engine) else sum(w.size for w in WHEELS[engine])


def extract_wheel(wheel_path: Path, target: Path, skip: tuple[str, ...] = ()) -> None:
    """Unzip a wheel into ``target``; refuses entries that would land outside it."""
    root = target.resolve()
    with zipfile.ZipFile(wheel_path) as zf:
        for info in zf.infolist():
            name = info.filename.replace("\\", "/")
            if any(name.startswith(p) for p in skip):
                continue
            dest = (root / name).resolve()
            if dest != root and root not in dest.parents:
                raise AddonError(f"{wheel_path.name}: unsafe path {info.filename!r}; refused")
            if info.is_dir():
                dest.mkdir(parents=True, exist_ok=True)
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out, CHUNK)


def install(engine: str, progress: Progress | None = None,
            cancelled: CancelCheck | None = None) -> None:
    """Download, check and extract the engine's wheels (no-op when installed).

    Extracts into ``lib.new`` and swaps it in only when every wheel checked
    out, so a failed or cancelled install never leaves a half-made ``lib``.
    """
    if installed(engine):
        return
    wheels = WHEELS[engine]
    total = sum(w.size for w in wheels)
    dl = _download_dir(engine)
    new = engine_dir(engine) / "lib.new"
    shutil.rmtree(new, ignore_errors=True)
    done = 0
    try:
        paths = []
        for w in wheels:
            path = dl / w.filename
            if not file_ok(path, w.sha256, w.size):
                fetch(wheel_url(w), path, w.sha256, w.size, progress=progress,
                      cancelled=cancelled, done_before=done, total=total)
            done += w.size
            if progress is not None:
                progress(done, total)
            paths.append(path)
        for path in paths:
            if cancelled is not None and cancelled():
                raise base.Cancelled()
            extract_wheel(path, new, SKIP_PREFIXES.get(engine, ()))
        (new / MARKER).write_text(json.dumps({"sha256": _pins(engine)}), encoding="utf-8")
        old = lib_dir(engine)
        shutil.rmtree(old, ignore_errors=True)
        os.replace(new, old)
    except BaseException:
        shutil.rmtree(new, ignore_errors=True)
        raise
    shutil.rmtree(dl, ignore_errors=True)
    log.info("voice add-on %s installed in %s", engine, lib_dir(engine))


def activate(engine: str) -> Path:
    """Put the engine's lib folder on sys.path (at the end). Raises when missing."""
    if not installed(engine):
        raise AddonError(f"the {engine} add-on is not downloaded")
    path = str(lib_dir(engine))
    if path not in sys.path:
        sys.path.append(path)
    return Path(path)


def fetch_files(engine: str, files: tuple[RemoteFile, ...], progress: Progress | None = None,
                cancelled: CancelCheck | None = None, done_before: int = 0,
                total: int = 0) -> None:
    """Download the voice/model ``files`` that are not there yet."""
    done = done_before
    for rf in files:
        dest = voices_dir(engine) / rf.name
        if not file_ok(dest, rf.sha256, rf.size):
            fetch(rf.url, dest, rf.sha256, rf.size, progress=progress, cancelled=cancelled,
                  done_before=done, total=total)
        done += rf.size
        if progress is not None:
            progress(done, total)


def missing_bytes(engine: str, files: tuple[RemoteFile, ...]) -> int:
    """Bytes still to download: the package (if needed) plus missing ``files``.

    Uses a size check only (hashing 100 MB on every menu refresh is too slow);
    ``fetch_files`` re-checks the hash before skipping a file.
    """
    missing = package_bytes(engine)
    for rf in files:
        dest = voices_dir(engine) / rf.name
        try:
            if dest.stat().st_size == rf.size:
                continue
        except OSError:
            pass
        missing += rf.size
    return missing


def onnx_session(model_path: Path, threads: int = base.ONNX_THREADS):
    """An onnxruntime session on ``threads`` CPU threads, no idle spinning.

    With one intra-op thread onnxruntime runs on the calling thread, so it
    keeps the TTS worker's below-normal priority.
    """
    import onnxruntime as ort
    so = ort.SessionOptions()
    so.intra_op_num_threads = max(1, int(threads))
    so.inter_op_num_threads = 1
    so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    so.add_session_config_entry("session.intra_op.allow_spinning", "0")
    so.add_session_config_entry("session.inter_op.allow_spinning", "0")
    so.log_severity_level = 3
    return ort.InferenceSession(str(model_path), sess_options=so,
                                providers=["CPUExecutionProvider"])


def size_text(n: int) -> str:
    """Bytes as "34 MB" for the menu."""
    return f"{max(1, round(n / 2**20))} MB" if n >= 2**20 else f"{max(1, round(n / 1024))} KB"
