"""Piper and Kokoro voice add-ons (app/tts/addons.py, piper.py, kokoro.py).

    python -m tools.neural_selftest [--files DIR] [--live]

Offline by default: PyPI and Hugging Face are replaced by a stand-in that
serves the files from the research downloads (``--files``, the folder with
dl/wheels and models/; also NEURAL_FILES). ``--live`` adds read-only checks
that every pin still matches PyPI and Hugging Face.

Checks: the add-ons are never imported when the app is imported; an engine is
unavailable before its download; a tampered wheel or a wrong PyPI digest is
refused and leaves nothing behind; download progress and cancel; the licence
filter; Piper and Kokoro synthesise 16-bit mono PCM at their sample rates.

Runs at below-normal priority with temporary APPDATA/LOCALAPPDATA; never plays
audio.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if sys.platform == "win32":
    ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x4000)

_TMP = tempfile.TemporaryDirectory(prefix="sca-neural-", ignore_cleanup_errors=True)
os.environ["APPDATA"] = str(Path(_TMP.name) / "roaming")
os.environ["LOCALAPPDATA"] = str(Path(_TMP.name) / "local")

from app.tts import addons, base  # noqa: E402
from app.tts import kokoro as kokoro_mod  # noqa: E402
from app.tts import piper as piper_mod  # noqa: E402

ADDON_MODULES = ("piper", "kokoro_onnx", "phonemizer", "espeakng_loader")
DEFAULT_FILES = Path(tempfile.gettempdir()) / "claude" / \
    "E--Users-Stacie-Documents-GitHub-Gremlin-Platforms" / \
    "44d71474-1b2a-4338-b2d6-94881160b653" / "scratchpad" / "voice"
PHRASE = "Feynmaline, nineteen deposits"

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))
    if not ok:
        failures.append(name)


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def fresh_dir(tag: str) -> None:
    """Point the add-on folder at a new empty LOCALAPPDATA."""
    os.environ["LOCALAPPDATA"] = tempfile.mkdtemp(prefix=f"{tag}-", dir=_TMP.name)


class Server:
    """Stand-in for PyPI and Hugging Face: url -> local file or bytes."""

    def __init__(self, files: Path) -> None:
        self.wheels = files / "dl" / "wheels"
        self.routes: dict[str, Path | bytes] = {}
        self.digest_override: dict[str, str] = {}
        self.requests: list[str] = []

    def open(self, url: str, timeout: float = 0):
        self.requests.append(url)
        if url.startswith("https://pypi.org/pypi/"):
            project, version = url.split("/")[4:6]
            urls = []
            for w in addons.WHEELS["piper"] + addons.WHEELS["kokoro"]:
                if w.project == project and w.version == version:
                    urls.append({"filename": w.filename, "url": "local://" + w.filename,
                                 "digests": {"sha256": self.digest_override.get(w.filename,
                                                                                w.sha256)}})
            return io.BytesIO(json.dumps({"urls": urls}).encode())
        if url.startswith("local://"):
            route = self.routes.get(url, self.wheels / url[8:])
        else:
            route = self.routes[url]
        if isinstance(route, bytes):
            return io.BytesIO(route)
        return open(route, "rb")


# ---- tests ------------------------------------------------------------------
def test_no_import_at_app_import() -> None:
    code = (f"import sys; sys.path.insert(0, {str(ROOT)!r}); import app.main, app.voice, app.tts, app.tts.addons, app.tts.piper, "
            "app.tts.kokoro; from app.tts import create_engine; "
            "[create_engine(e).voices() for e in ('piper', 'kokoro')]; "
            f"print([m for m in {ADDON_MODULES!r} if m in sys.modules])")
    env = dict(os.environ)
    r = subprocess.run([sys.executable, "-I", "-c", code], cwd=ROOT, env=env,
                       capture_output=True, text=True, timeout=120)
    check("app import loads no add-on module", r.returncode == 0 and r.stdout.strip() == "[]",
          (r.stdout + r.stderr).strip()[-300:])
    # No static import statement anywhere in app/ (PyInstaller would follow it).
    bad = []
    for path in (ROOT / "app").rglob("*.py"):
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            s = line.strip()
            for m in ADDON_MODULES:
                if s.startswith((f"import {m}", f"from {m} ", f"from {m}.")):
                    bad.append(f"{path.relative_to(ROOT)}:{n}")
    check("no static add-on import in app/", not bad, ", ".join(bad))


def test_unavailable_before_download() -> None:
    fresh_dir("unavail")
    for eng, voice in ((piper_mod.PiperEngine(), "en_US-joe-medium"),
                       (kokoro_mod.KokoroEngine(), "am_michael")):
        need = eng.needs_download(voice)
        check(f"{eng.id}: unavailable before download", not eng.available()
              and eng.unavailable_reason().startswith("Add-on not downloaded"), eng.unavailable_reason())
        check(f"{eng.id}: download size shown ({addons.size_text(need)})", need > 30 * 2**20)
        try:
            eng.synth(PHRASE, voice, 1.0)
            check(f"{eng.id}: synth refused before download", False, "no error")
        except base.EngineError as exc:
            check(f"{eng.id}: synth refused before download", True, str(exc))
        try:
            addons.activate(eng.id)
            check(f"{eng.id}: activate refused before download", False)
        except addons.AddonError:
            check(f"{eng.id}: activate refused before download", True)


def test_sha256_refusal(server: Server) -> None:
    fresh_dir("tamper")
    first = addons.WHEELS["piper"][0]
    data = bytearray((server.wheels / first.filename).read_bytes())
    data[len(data) // 2] ^= 0xFF
    server.routes["local://" + first.filename] = bytes(data)
    try:
        addons.install("piper")
        check("tampered wheel refused", False, "installed")
    except addons.AddonError as exc:
        check("tampered wheel refused", "sha256" in str(exc), str(exc))
    eng_dir = addons.engine_dir("piper")
    left = [p.name for p in eng_dir.rglob("*") if p.is_file()] if eng_dir.exists() else []
    check("tampered wheel leaves no file and no lib", not left and not addons.installed("piper"),
          ", ".join(left))
    del server.routes["local://" + first.filename]

    server.digest_override[first.filename] = "0" * 64
    try:
        addons.install("piper")
        check("wrong PyPI digest refused", False, "installed")
    except addons.AddonError as exc:
        check("wrong PyPI digest refused", "different sha256" in str(exc), str(exc))
    server.digest_override.clear()

    # A voice file with the wrong hash is refused too.
    dest = addons.voices_dir("piper") / "x.onnx"
    url = "https://huggingface.co/test/x.onnx"
    server.routes[url] = b"not the model"
    try:
        addons.fetch(url, dest, "ab" * 32, 13)
        check("tampered voice file refused", False)
    except addons.AddonError:
        check("tampered voice file refused", not dest.exists()
              and not dest.with_name("x.onnx.part").exists())

    # A wheel whose entries escape the lib folder is refused.
    import zipfile
    evil = Path(_TMP.name) / "evil.whl"
    with zipfile.ZipFile(evil, "w") as zf:
        zf.writestr("../../escaped.txt", "x")
    target = Path(_TMP.name) / "evil-lib"
    try:
        addons.extract_wheel(evil, target)
        check("wheel path escape refused", False)
    except addons.AddonError:
        check("wheel path escape refused", not (Path(_TMP.name).parent / "escaped.txt").exists())


def test_progress_and_cancel(server: Server) -> None:
    fresh_dir("cancel")
    eng = piper_mod.PiperEngine()
    calls: list[tuple[int, int]] = []

    def cancel_soon() -> bool:
        return len(calls) >= 5

    try:
        eng.download("en_US-joe-medium", progress=lambda g, t: calls.append((g, t)),
                     cancelled=cancel_soon)
        check("cancel stops the download", False, "finished")
    except base.Cancelled:
        check("cancel stops the download", True, f"after {len(calls)} progress calls")
    left = [p.name for p in addons.engine_dir("piper").rglob("*") if p.is_file()
            and p.suffix in (".part", ".whl") and not addons.file_ok(p, *_pin_of(p.name))]
    check("cancel leaves no partial file and no lib", not left and not addons.installed("piper"),
          ", ".join(left))

    # Full package download with progress (voice download needs a real model:
    # see test_synth).
    calls.clear()
    addons.install("piper", progress=lambda g, t: calls.append((g, t)))
    total = sum(w.size for w in addons.WHEELS["piper"])
    mono = all(b[0] >= a[0] for a, b in zip(calls, calls[1:]))
    check("progress rises to the total", bool(calls) and mono and calls[-1] == (total, total),
          f"{len(calls)} calls, last {calls[-1] if calls else None}")
    check("installed after download", addons.installed("piper") and addons.package_bytes("piper") == 0)
    check("partial-download folder removed", not (addons.engine_dir("piper") / "download").exists())


def _pin_of(filename: str) -> tuple[str, int]:
    for w in addons.WHEELS["piper"] + addons.WHEELS["kokoro"]:
        if w.filename == filename:
            return w.sha256, w.size
    return "", 0


def test_licence_filter(files: Path) -> None:
    L = piper_mod.licence_allowed
    allowed = ["public domain", "CC0", "CC BY 4.0", "CC-BY-4.0",
               "https://creativecommons.org/licenses/by/4.0/"]
    refused = ["CC-BY-SA 4.0 International", "http://creativecommons.org/licenses/by-nc-sa/4.0/",
               "CC BY-NC-SA 4.0", "https://creativecommons.org/licenses/by-nc/4.0/", "See URL",
               "See LICENSE file", "https://www.apache.org/licenses/LICENSE-2.0.txt", "", "research only",
               "https://www.cstr.ed.ac.uk/projects/blizzard/2013/lessac_blizzard2013/license.html"]
    check("licence filter allows PD/CC0/CC-BY", all(L(t) for t in allowed),
          str([t for t in allowed if not L(t)]))
    check("licence filter refuses NC/SA/unknown", not any(L(t) for t in refused),
          str([t for t in refused if L(t)]))
    keys = [v.key for v in piper_mod.catalogue()]
    check("catalogue: every offered voice passes the filter",
          len(keys) == len(piper_mod.PIPER_VOICES) and len(keys) >= 10, f"{len(keys)} voices")
    check("catalogue: non-commercial / Blizzard voices absent",
          not {"en_US-ryan-medium", "en_US-lessac-medium", "en_US-hfc_male-medium"} & set(keys))
    nc = piper_mod.PiperVoiceInfo("en_US-x-medium", "CC BY-NC-SA 4.0", 1, 1, "0" * 64, 1, "0" * 64)
    eng = piper_mod.PiperEngine(voices=(*piper_mod.PIPER_VOICES, nc))
    check("engine drops an injected non-commercial voice",
          "en_US-x-medium" not in [v.id for v in eng.voices()])
    vj = files / "models" / "piper" / "voices.json"
    if vj.is_file():
        data = json.loads(vj.read_text(encoding="utf-8"))
        # voices.json lists a stale size for libritts_r (the pin is the real
        # file's size and sha256 at REVISION, from the Hugging Face API).
        stale = {"en_US-libritts_r-medium"}
        wrong = []
        for v in piper_mod.PIPER_VOICES:
            entry = data.get(v.key)
            onnx = f"{v.path}{v.key}.onnx"
            if not entry or onnx not in entry["files"] or (
                    v.key not in stale and entry["files"][onnx]["size_bytes"] != v.onnx_size):
                wrong.append(v.key)
        check("catalogue matches voices.json (keys, paths, sizes)", not wrong, ", ".join(wrong))
    for v in eng.voices()[:1]:
        check("voice row shows licence and size", "CC" in v.detail or "public" in v.detail, v.detail)


def _pcm_ok(name: str, audio: base.Audio | None, rate: int) -> float:
    import numpy as np
    ok = (audio is not None and audio.sample_format == base.INT16 and audio.channels == 1
          and audio.sample_rate == rate and len(audio.data) % 2 == 0)
    secs = audio.seconds if audio else 0.0
    rms = float(np.sqrt(np.mean(np.frombuffer(audio.data, "<i2").astype("f8") ** 2))) if ok else 0
    check(f"{name}: 16-bit mono PCM at {rate} Hz, speech length", ok and 1.0 < secs < 5.0 and rms > 300,
          f"{secs:.2f} s, rms {rms:.0f}")
    return secs


def test_synth(server: Server, files: Path) -> None:
    # Piper: the research voice (lessac) stands in for an offered voice; it is
    # given a test licence (CC0) only so the catalogue accepts it here.
    fresh_dir("piper")
    model = files / "models" / "piper" / "en_US-lessac-medium.onnx"
    cfgf = Path(str(model) + ".json")
    if not model.is_file():
        check("piper: research model present", False, str(model))
        return
    stand_in = piper_mod.PiperVoiceInfo("en_US-lessac-medium", "CC0", 1,
                                        model.stat().st_size, sha(model),
                                        cfgf.stat().st_size, sha(cfgf))
    eng = piper_mod.PiperEngine(voices=(stand_in,))
    for rf in stand_in.files():
        server.routes[rf.url] = model if rf.name.endswith(".onnx") else cfgf
    calls: list[tuple[int, int]] = []
    need = eng.needs_download(stand_in.key)
    eng.download(stand_in.key, progress=lambda g, t: calls.append((g, t)))
    check("piper: one progress bar over package + voice",
          calls[-1] == (need, need) and all(t == need for _, t in calls), f"{calls[-1]} of {need}")
    check("piper: available and nothing left to download",
          eng.available() and eng.needs_download(stand_in.key) == 0)
    normal = _pcm_ok("piper", eng.synth(PHRASE, stand_in.key, 1.0), 22050)
    fast = eng.synth(PHRASE, stand_in.key, 2.0)
    check("piper: speed 2.0 is shorter", fast is not None and fast.seconds < normal * 0.75,
          f"{fast.seconds if fast else 0:.2f} s vs {normal:.2f} s")
    check("piper: empty text gives no audio", eng.synth("  ", stand_in.key, 1.0) is None)
    session = next(iter(eng._loaded.values())).session
    check("piper: own ONNX session (CPU)", session.get_providers() == ["CPUExecutionProvider"])

    # Kokoro: int8 model from the research download, am_michael from HF.
    fresh_dir("kokoro")
    km = files / "models" / "kokoro" / "model_quantized.onnx"
    kv = files.parent / "w9n" / "kv" / "am_michael.bin"
    if not (km.is_file() and kv.is_file()):
        check("kokoro: research model and voice present", False, f"{km} / {kv}")
        return
    server.routes[kokoro_mod.MODEL.url] = km
    server.routes[kokoro_mod.voice_file("am_michael").url] = kv
    keng = kokoro_mod.KokoroEngine()
    keng.download("am_michael")
    check("kokoro: available after download", keng.available()
          and keng.needs_download("am_michael") == 0)
    k1 = _pcm_ok("kokoro", keng.synth(PHRASE, "am_michael", 1.0), 24000)
    k2 = keng.synth(PHRASE, "am_michael", 1.6)
    check("kokoro: speed 1.6 is shorter", k2 is not None and k2.seconds < k1 * 0.85,
          f"{k2.seconds if k2 else 0:.2f} s vs {k1:.2f} s")
    try:
        keng.synth(PHRASE, "bf_emma", 1.0)
        check("kokoro: voice not downloaded is refused", False)
    except base.EngineError as exc:
        check("kokoro: voice not downloaded is refused", "not downloaded" in str(exc))
    leaked = [m for m in ("phonemizer", "kokoro_onnx") if m in sys.modules]
    check("kokoro: add-on modules loaded only now", bool(leaked))


def test_live() -> None:
    for w in addons.WHEELS["piper"] + addons.WHEELS["kokoro"]:
        try:
            url = addons.wheel_url(w)
            check(f"live: PyPI pin {w.filename}", url.startswith("https://files.pythonhosted.org/"))
        except addons.AddonError as exc:
            check(f"live: PyPI pin {w.filename}", False, str(exc))
    import urllib.request

    def paths_info(repo: str, rev: str, paths: list[str]) -> dict[str, dict]:
        req = urllib.request.Request(
            f"https://huggingface.co/api/models/{repo}/paths-info/{rev}",
            data=json.dumps({"paths": paths}).encode(), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return {e["path"]: e for e in json.load(resp)}
    info = paths_info("rhasspy/piper-voices", piper_mod.REVISION,
                      [v.path + v.key + ".onnx" for v in piper_mod.PIPER_VOICES])
    bad = [v.key for v in piper_mod.PIPER_VOICES
           if info.get(v.path + v.key + ".onnx", {}).get("lfs", {}).get("oid") != v.onnx_sha256]
    check("live: Piper voice sha256 pins match Hugging Face", not bad, ", ".join(bad))
    names = ["onnx/model_quantized.onnx"] + [f"voices/{n}.bin" for n in kokoro_mod.KOKORO_VOICES]
    info = paths_info("onnx-community/Kokoro-82M-v1.0-ONNX", kokoro_mod.REVISION, names)
    want = {"onnx/model_quantized.onnx": kokoro_mod.MODEL.sha256}
    want.update({f"voices/{n}.bin": s for n, (_, s) in kokoro_mod.KOKORO_VOICES.items()})
    bad = [p for p, s in want.items() if info.get(p, {}).get("lfs", {}).get("oid") != s]
    check("live: Kokoro sha256 pins match Hugging Face", not bad, ", ".join(bad))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--files", default=os.environ.get("NEURAL_FILES", str(DEFAULT_FILES)))
    ap.add_argument("--live", action="store_true")
    args = ap.parse_args()
    files = Path(args.files)
    tests = [test_no_import_at_app_import, test_unavailable_before_download]
    server = Server(files)
    if args.live:
        tests.append(test_live)
    if (files / "dl" / "wheels").is_dir():
        tests += [lambda: test_licence_filter(files), lambda: test_sha256_refusal(server),
                  lambda: test_progress_and_cancel(server), lambda: test_synth(server, files)]
    else:
        tests.append(lambda: test_licence_filter(files))
        print(f"SKIP  offline download/synth tests: no research files in {files}")
    real_open = addons._open
    for t in tests:
        is_live = t is test_live
        addons._open = real_open if is_live else server.open
        try:
            t()
        except Exception:      # noqa: BLE001
            check(getattr(t, "__name__", "test"), False, traceback.format_exc()[-800:])
        finally:
            addons._open = real_open
    offline_net = [u for u in server.requests if not u.startswith(("https://pypi.org/", "local://",
                                                                    "https://huggingface.co/"))]
    check("only PyPI / Hugging Face URLs requested", not offline_net, ", ".join(offline_net))
    print(f"\n{'ALL PASS' if not failures else f'{len(failures)} FAILED: ' + ', '.join(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
