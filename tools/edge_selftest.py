"""Microsoft online voices (app/tts/edge.py) work, and fail clearly.

    python -m tools.edge_selftest            # offline, fake transport
    python -m tools.edge_selftest --live     # also asks Microsoft for real
    python -m tools.edge_selftest --live --edge-path <site-packages with edge_tts>

Runs against temporary APPDATA/LOCALAPPDATA folders and never plays audio.
Offline checks drive EdgeEngine with a fake transport:

* the voice list keeps English voices only, is cached to disk and read back by
  a new engine, and a short built-in list is shown before the first fetch;
* speed becomes edge-tts's rate string (1.0 -> "+0%", 0.5 -> "-50%", ...);
* synth on a worker thread returns the streamed MP3 bytes as Audio.mp3;
* a slow answer ends in EdgeError (an EngineError) within the timeout, and so
  do a transport error, an empty answer, and edge-tts missing.

--live synthesises the test phrase to an MP3 in the temp folder (no playback).
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_TMP = tempfile.TemporaryDirectory(prefix="ca-edge-")
os.environ["APPDATA"] = str(Path(_TMP.name) / "Roaming")
os.environ["LOCALAPPDATA"] = str(Path(_TMP.name) / "Local")

TEST_PHRASE = "Feynmaline, nineteen deposits"

FAKE_VOICES = [
    {"ShortName": "en-US-AriaNeural", "Gender": "Female",
     "VoiceTag": {"VoicePersonalities": ["Positive", "Confident"]}},
    {"ShortName": "de-DE-KatjaNeural", "Gender": "Female"},
    {"ShortName": "en-GB-RyanNeural", "Gender": "Male"},
    {"ShortName": "en-AU-NatashaNeural", "Gender": "Female"},
    {"ShortName": "fr-FR-HenriNeural", "Gender": "Male"},
]
FAKE_MP3 = [b"ID3\x04\x00\x00", b"\xff\xf3frame1", b"\xff\xf3frame2"]


class FakeTransport:
    def __init__(self, delay: float = 0.0, fail: Exception | None = None,
                 chunks: list[bytes] | None = None) -> None:
        self.delay = delay
        self.fail = fail
        self.chunks = FAKE_MP3 if chunks is None else chunks
        self.calls: list[tuple[str, str, str]] = []
        self.list_calls = 0

    async def list_voices(self) -> list[dict]:
        self.list_calls += 1
        await asyncio.sleep(self.delay)
        if self.fail:
            raise self.fail
        return list(FAKE_VOICES)

    async def stream(self, text: str, voice: str, rate: str):
        self.calls.append((text, voice, rate))
        await asyncio.sleep(self.delay)
        if self.fail:
            raise self.fail
        for c in self.chunks:
            yield c


def _check(label: str, ok: bool, detail: str = "") -> int:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{'  ' + detail if detail else ''}")
    return 0 if ok else 1


def _on_worker(fn):
    """Run fn on a plain thread (like the TTS worker); return (result, error)."""
    out: dict = {}

    def run():
        try:
            out["r"] = fn()
        except BaseException as exc:      # noqa: BLE001 - reported by the test
            out["e"] = exc
    t = threading.Thread(target=run, name="tts-worker-test")
    t.start()
    t.join(30)
    return out.get("r"), out.get("e")


def offline() -> int:
    from app.tts import base, edge
    fails = 0
    print("edge engine, offline (fake transport)")

    # --- rate strings
    cases = {1.0: "+0%", 1.25: "+25%", 0.5: "-50%", 2.0: "+100%", 0.8: "-20%",
             1.1: "+10%", 3.0: "+100%", 0.1: "-50%", float("nan"): "+0%", "x": "+0%"}
    got = {k: edge.rate_string(k) for k in cases}           # type: ignore[arg-type]
    bad = {k: v for k, v in got.items() if v != cases[k]}
    fails += _check("speed -> rate string", not bad, str(bad) if bad else "")

    # --- identity
    eng = edge.EdgeEngine(FakeTransport())
    fails += _check("id/label/online", eng.id == "edge" and eng.online
                    and "sends the phrase to Microsoft" in eng.label, eng.label)
    fails += _check("is a base.Engine, no download needed",
                    isinstance(eng, base.Engine) and eng.needs_download("en-US-AriaNeural") == 0)

    # --- voice list
    before = eng.voices()
    fails += _check("built-in list before the first fetch",
                    len(before) >= 4 and all(v.id.startswith("en-") for v in before),
                    f"{len(before)} voices")
    fake = FakeTransport()
    eng = edge.EdgeEngine(fake)
    voices, err = _on_worker(eng.refresh_voices)
    ids = [v.id for v in voices or []]
    fails += _check("refresh keeps English only", err is None and sorted(ids) == sorted(
        ["en-US-AriaNeural", "en-GB-RyanNeural", "en-AU-NatashaNeural"]), f"{ids} {err!r}")
    aria = next((v for v in voices or [] if v.id == "en-US-AriaNeural"), None)
    fails += _check("voice name and detail", aria is not None and aria.name == "Aria (en-US)"
                    and "Female" in aria.detail and "Confident" in aria.detail,
                    repr(aria))
    cache = Path(os.environ["LOCALAPPDATA"]) / "SC Assistant" / "voices" / "edge" / "voices.json"
    fails += _check("voice list cached to disk", cache.is_file(), str(cache))
    fresh = FakeTransport()
    eng2 = edge.EdgeEngine(fresh)
    ids2 = [v.id for v in eng2.voices()]
    fails += _check("new engine reads the cache, no network",
                    ids2 == ids and fresh.list_calls == 0, f"{ids2}")
    eng2.voices()
    fails += _check("second voices() call uses memory", fresh.list_calls == 0)

    # --- synth returns MP3
    fake = FakeTransport()
    eng = edge.EdgeEngine(fake)
    audio, err = _on_worker(lambda: eng.synth(TEST_PHRASE, "en-GB-RyanNeural", 1.5))
    fails += _check("synth on a worker thread returns Audio.mp3",
                    err is None and isinstance(audio, base.Audio) and audio.is_mp3
                    and audio.data == b"".join(FAKE_MP3), f"{audio!r:.80} {err!r}")
    fails += _check("phrase, voice and rate reach the transport",
                    fake.calls == [(TEST_PHRASE, "en-GB-RyanNeural", "+50%")], str(fake.calls))
    _, err = _on_worker(lambda: eng.synth(TEST_PHRASE, "", 1.0))
    fails += _check("empty voice id uses the default voice",
                    err is None and fake.calls[-1][1] == edge.DEFAULT_VOICE, str(fake.calls[-1]))
    r, err = _on_worker(lambda: eng.synth("   ", "en-US-AriaNeural", 1.0))
    fails += _check("blank text: nothing to say (None), no network",
                    r is None and err is None and len(fake.calls) == 2)

    # --- failures are EdgeError, fast
    eng = edge.EdgeEngine(FakeTransport(delay=5.0), synth_timeout=0.3, list_timeout=0.3)
    t0 = time.monotonic()
    _, err = _on_worker(lambda: eng.synth(TEST_PHRASE, "en-US-AriaNeural", 1.0))
    took = time.monotonic() - t0
    fails += _check("slow answer -> EdgeError within the timeout",
                    isinstance(err, edge.EdgeError) and isinstance(err, base.EngineError)
                    and took < 2.0 and "within" in str(err), f"{took:.2f} s, {err}")
    _, err = _on_worker(eng.refresh_voices)
    fails += _check("slow voice list -> EdgeError", isinstance(err, edge.EdgeError), str(err))

    eng = edge.EdgeEngine(FakeTransport(fail=OSError("Cannot connect to host")))
    _, err = _on_worker(lambda: eng.synth(TEST_PHRASE, "en-US-AriaNeural", 1.0))
    fails += _check("transport error -> EdgeError with the reason",
                    isinstance(err, edge.EdgeError) and "Cannot connect" in str(err), str(err))
    eng = edge.EdgeEngine(FakeTransport(chunks=[]))
    _, err = _on_worker(lambda: eng.synth(TEST_PHRASE, "en-US-AriaNeural", 1.0))
    fails += _check("no audio -> EdgeError", isinstance(err, edge.EdgeError), str(err))
    voices_before = [v.id for v in edge.EdgeEngine(FakeTransport()).voices()]
    eng = edge.EdgeEngine(FakeTransport(fail=OSError("down")))
    _on_worker(eng.refresh_voices)
    fails += _check("failed refresh keeps the cached list",
                    [v.id for v in eng.voices()] == voices_before)

    # --- edge-tts missing
    real = edge.edge_tts_installed
    edge.edge_tts_installed = lambda: False                 # type: ignore[assignment]
    try:
        eng = edge.EdgeEngine()
        _, err = _on_worker(lambda: eng.synth(TEST_PHRASE, "en-US-AriaNeural", 1.0))
        fails += _check("edge-tts missing: unavailable, synth -> EdgeError",
                        not eng.available() and bool(eng.unavailable_reason())
                        and isinstance(err, edge.EdgeError), str(err))
    finally:
        edge.edge_tts_installed = real                      # type: ignore[assignment]
    return fails


def live() -> int:
    from app.tts import edge
    fails = 0
    print("edge engine, live (sends the test phrase to Microsoft)")
    if not edge.edge_tts_installed():
        return _check("edge-tts importable", False, "use --edge-path")
    eng = edge.EdgeEngine()
    t0 = time.monotonic()
    voices, err = _on_worker(eng.refresh_voices)
    fails += _check("online English voice list", err is None and len(voices or []) >= 10,
                    f"{len(voices or [])} voices, {time.monotonic() - t0:.2f} s {err or ''}")
    for speed in (1.0, 1.5):
        t0 = time.monotonic()
        audio, err = _on_worker(lambda s=speed: eng.synth(TEST_PHRASE, "en-GB-RyanNeural", s))
        took = time.monotonic() - t0
        data = audio.data if audio else b""
        out = Path(_TMP.name) / f"edge_{speed}.mp3"
        out.write_bytes(data)
        mp3 = data[:3] == b"ID3" or (len(data) > 1 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0)
        fails += _check(f"MP3 at speed {speed}", err is None and mp3 and len(data) > 2000,
                        f"{len(data)} bytes, {took:.2f} s, {out} {err or ''}")
    _, err = _on_worker(lambda: eng.synth(TEST_PHRASE, "en-US-NoSuchVoiceNeural", 1.0))
    fails += _check("unknown voice -> EdgeError", isinstance(err, edge.EdgeError), str(err))
    return fails


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--edge-path", help="extra folder holding edge_tts (research venv)")
    a = ap.parse_args()
    if a.edge_path:
        sys.path.append(a.edge_path)
    fails = offline()
    if a.live:
        fails += live()
    print("ALL PASS" if not fails else f"{fails} FAILED")
    return 1 if fails else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        _TMP.cleanup()
