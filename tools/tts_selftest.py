"""VOICE engine checks: phrases, the Voice facade, the TTS worker, the Windows
voices and the player.

    python -m tools.tts_selftest

Nothing is ever audible: every voice and player runs at volume 0. Needs a
Windows desktop session (the Windows voices and an audio output device).
"""
from __future__ import annotations

from tools import _testguard

_testguard.install()        # first: no focus, no hotkeys

import importlib  # noqa: E402
import math  # noqa: E402
import os  # noqa: E402
import struct  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
# Never the user's folders: config and add-ons resolve from these.
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="ca_tts_selftest_")
os.environ["LOCALAPPDATA"] = tempfile.mkdtemp(prefix="ca_tts_selftest_local_")

from PySide6.QtCore import QThread, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def _pump_until(cond, seconds: float) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        QApplication.processEvents()
        if cond():
            return True
        time.sleep(0.005)
    QApplication.processEvents()
    return bool(cond())


def _check(label: str, ok: bool, detail: str = "") -> int:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{'  ' + detail if detail else ''}")
    return 0 if ok else 1


# ---- test engines ---------------------------------------------------------
def _engines():
    from app.tts.base import INT16, Audio, Engine, EngineError

    class RaisingEngine(Engine):
        id = "piper"
        label = "Raising test engine"

        def available(self):
            return True

        def voices(self):
            return []

        def synth(self, text, voice_id, speed):
            raise EngineError("model exploded")

    class BrokenReadyEngine(RaisingEngine):
        def needs_download(self, voice_id):
            raise RuntimeError("index unreadable")

    class SlowEngine(Engine):
        id = "kokoro"
        label = "Slow test engine"

        def __init__(self, delay=0.3):
            self.delay = delay
            self.calls: list[str] = []
            self.threads: set[int] = set()

        def available(self):
            return True

        def synth(self, text, voice_id, speed):
            self.calls.append(text)
            self.threads.add(threading.get_ident())
            time.sleep(self.delay)
            return Audio(text.encode(), 22050, 1, INT16)

    class ToneEngine(Engine):
        id = "kokoro"
        label = "Tone test engine"

        def available(self):
            return True

        def synth(self, text, voice_id, speed):
            return _tone(0.25)

    return RaisingEngine, BrokenReadyEngine, SlowEngine, ToneEngine


def _tone(seconds: float, rate: int = 22050):
    from app.tts.base import INT16, Audio

    n = int(seconds * rate)
    data = struct.pack(f"<{n}h", *(int(8000 * math.sin(2 * math.pi * 440 * i / rate))
                                   for i in range(n)))
    return Audio(data, rate, 1, INT16)


def _silent_mp3(frames: int = 40) -> bytes:
    """MPEG-1 Layer III, 128 kbps, 44.1 kHz, mono; zero side info = silence."""
    header = bytes((0xFF, 0xFB, 0x90, 0xC0))
    frame = header + bytes(417 - len(header))       # 144 * 128000 / 44100 = 417
    return frame * frames


# ---- checks ---------------------------------------------------------------
def check_phrases() -> int:
    from app.tts import phrases as p

    failures = 0
    cases = [
        (("Borase", 3, 14400, "count_after"), "Borase, times 3"),
        (("Borase", 1, 4800, "count_after"), "Borase"),
        (("Borase", 3, 14400, "count_before"), "Three Borase"),
        (("Borase", 1, 4800, "count_before"), "Borase"),
        (("Feynmaline", 19, 57000, "count_before"), "Nineteen Feynmaline"),
        (("Borase", 3, 14400, "with_signature"), "Borase, three rocks, fourteen thousand four hundred"),
        (("Borase", 1, 4800, "with_signature"), "Borase, one rock, four thousand eight hundred"),
        (("ROC deposit", 19, 76000, "with_signature", "deposits"),
         "ROC deposit, nineteen deposits, seventy-six thousand"),
        (("Borase", 3, None, "with_signature"), "Borase, three rocks"),
        (("", 3, 14400, "with_signature"), ""),
        (("Borase", 3, 14400, "nonsense"), "Borase, times 3"),
    ]
    for args, want in cases:
        got = p.spoken_text(*args)
        failures += _check(f"spoken_text{args!r}", got == want, f"(got {got!r})")
    for n, want in ((0, "zero"), (19, "nineteen"), (21, "twenty-one"), (100, "one hundred"),
                    (76000, "seventy-six thousand"), (14400, "fourteen thousand four hundred"),
                    (1_234_567, "one million two hundred thirty-four thousand five hundred sixty-seven")):
        failures += _check(f"number_words({n})", p.number_words(n) == want,
                           f"(got {p.number_words(n)!r})")
    failures += _check("three styles", p.STYLES == ("count_after", "count_before", "with_signature"))
    failures += _check("unit_for kinds",
                       (p.unit_for("ship", 3), p.unit_for("roc", 1), p.unit_for("fps", 19))
                       == ("rocks", "deposit", "deposits"))
    tests = [p.test_phrase(s) for s in p.STYLES]
    failures += _check("TEST phrase per style",
                       tests == ["Feynmaline, times 19", "Nineteen Feynmaline",
                                 "Feynmaline, nineteen deposits, fifty-seven thousand"],
                       f"(got {tests})")
    return failures


def check_old_callers() -> int:
    """app.voice keeps the API main.py and the self-tests use."""
    import app.voice as v

    failures = 0
    failures += _check("app.voice.spoken_text('Borase', 3)",
                       v.spoken_text("Borase", 3) == "Borase, times 3")
    failures += _check("app.voice.spoken_text('Borase')", v.spoken_text("Borase") == "Borase")
    failures += _check("app.voice.spoken_text('', 2)", v.spoken_text("", 2) == "")
    voice = v.Voice()
    voice.set_volume(0.0)
    names = ("say", "stop", "set_enabled", "set_volume", "available", "enabled", "volume")
    failures += _check("Voice() keeps its old API", all(hasattr(voice, n) for n in names))
    voice.set_enabled(False)
    failures += _check("say() is a no-op when voice is off", voice.say("Borase") is False)
    failures += _check("enabled/volume round-trip", voice.enabled is False and voice.volume == 0.0)
    try:
        importlib.import_module("app.main")    # imports Voice, spoken_text from app.voice
        ok, detail = True, ""
    except Exception as exc:        # noqa: BLE001
        ok, detail = False, f"({exc})"
    failures += _check("app.main imports with the new app.voice", ok, detail)
    voice.shutdown()
    return failures


def _recording_windows(voice):
    """Wrap the facade's real Windows engine so each speak() is recorded."""
    win = voice.engine("windows")
    calls: list[tuple] = []
    real = win.speak

    def speak(text, voice_id, speed, volume):
        calls.append((text, voice_id, speed, volume))
        return real(text, voice_id, speed, volume)

    win.speak = speak
    return win, calls


def check_facade_fallback() -> int:
    from app.voice import Voice

    RaisingEngine, BrokenReadyEngine, _Slow, _Tone = _engines()
    failures = 0

    voice = Voice(engine="piper", voice="en_US-lessac-medium", volume=0.0)
    win, calls = _recording_windows(voice)
    notices: list[str] = []
    voice.notice.connect(notices.append)
    voice._engines["piper"] = RaisingEngine()
    failures += _check("say() with a raising engine is accepted", voice.say("Borase, times 3") is True)
    _pump_until(lambda: calls, 5)
    failures += _check("engine failure falls back to a Windows voice",
                       [c[0] for c in calls] == ["Borase, times 3"], f"(calls {calls})")
    failures += _check("fallback uses the Windows default voice at volume 0",
                       bool(calls) and calls[0][1] == "" and calls[0][3] == 0.0)
    failures += _check("fallback is reported", bool(notices) and "model exploded" in notices[-1],
                       f"({notices})")

    calls.clear()
    voice._engines["piper"] = BrokenReadyEngine()
    voice.say("Agricium")
    failures += _check("an engine whose checks raise falls back too",
                       [c[0] for c in calls] == ["Agricium"], f"(calls {calls})")

    calls.clear()
    voice._engines["piper"] = None        # module missing / failed to import
    voice.say("Bexalite")
    failures += _check("a missing engine falls back to Windows",
                       [c[0] for c in calls] == ["Bexalite"], f"(calls {calls})")
    _pump_until(lambda: not win.speaking(), 10)
    voice.shutdown()
    return failures


def check_facade_plays() -> int:
    """say() on a synth engine: worker -> audio_ready -> Player, to the end."""
    from app.voice import Voice

    _r, _b, SlowEngine, ToneEngine = _engines()
    failures = 0
    voice = Voice(engine="kokoro", volume=0.0)
    voice._engines["kokoro"] = ToneEngine()
    _win, calls = _recording_windows(voice)
    voice.say("Borase")
    worker = voice._worker
    failures += _check("worker runs below normal priority",
                       worker is not None and _pump_until(worker.isRunning, 2)
                       and worker.priority() == QThread.Priority.LowPriority,
                       f"({worker.priority() if worker else None})")
    player_seen = _pump_until(lambda: voice._player is not None, 5)
    player = voice._player
    finished = []
    if player is not None:
        player.finished.connect(lambda: finished.append(1))
    done = player_seen and _pump_until(lambda: finished or not player.playing(), 5)
    failures += _check("synth engine audio played through the Player at volume 0",
                       done and player.volume == 0.0 and not calls,
                       f"(player {player_seen}, windows calls {calls})")

    # stop() while a phrase is being made: nothing plays afterwards.
    slow = SlowEngine(0.3)
    voice._engines["kokoro"] = slow
    voice.say("Hadanite")
    _pump_until(lambda: slow.calls, 2)
    voice.stop()
    _pump_until(lambda: False, 0.5)
    failures += _check("stop() drops the phrase being made",
                       not voice._pending and not voice._player.playing() and not calls)
    voice.shutdown()
    failures += _check("shutdown() ends the worker", not worker.isRunning())
    return failures


def check_worker() -> int:
    from app.tts.worker import TtsWorker

    _r, _b, SlowEngine, _t = _engines()
    failures = 0
    worker = TtsWorker()
    got: list[tuple[bytes, int]] = []
    worker.audio_ready.connect(lambda audio, job: got.append((audio.data, job)))
    worker.start_worker()
    engine = SlowEngine(0.3)

    ticks = [0]
    timer = QTimer()
    timer.setInterval(10)
    timer.timeout.connect(lambda: ticks.__setitem__(0, ticks[0] + 1))
    timer.start()

    t0 = time.perf_counter()
    worker.submit(engine, "a", "", 1.0)
    _pump_until(lambda: engine.calls, 2)            # "a" is being made
    worst = 0.0
    for text in ("b", "c", "d"):
        s = time.perf_counter()
        last = worker.submit(engine, text, "", 1.0)
        worst = max(worst, time.perf_counter() - s)
    _pump_until(lambda: got, 3)
    _pump_until(lambda: False, 0.4)                 # anything late would show up now
    elapsed = time.perf_counter() - t0
    timer.stop()

    failures += _check("only the newest phrase is emitted",
                       [g[0] for g in got] == [b"d"] and got[0][1] == last, f"(got {got})")
    failures += _check("stale phrases are dropped, never synthesised",
                       engine.calls == ["a", "d"] and worker.dropped == 3,
                       f"(calls {engine.calls}, dropped {worker.dropped})")
    failures += _check("synth runs off the GUI thread",
                       threading.main_thread().ident not in engine.threads)
    failures += _check("submit() never blocks the GUI thread", worst < 0.02, f"({worst * 1000:.1f} ms)")
    # 10 ms timer over ~0.7 s of synthesis: a blocked GUI thread would tick ~0 times.
    failures += _check("GUI event loop keeps running during synthesis",
                       ticks[0] >= elapsed * 100 * 0.4, f"({ticks[0]} ticks in {elapsed:.2f} s)")
    worker.cancel()
    worker.shutdown()
    failures += _check("worker stops on shutdown()", not worker.isRunning())
    return failures


def check_windows_engine() -> int:
    from app.tts.windows import WindowsEngine, speed_to_rate, voice_detail

    from PySide6.QtTextToSpeech import QTextToSpeech

    failures = 0
    eng = WindowsEngine()
    names = eng.engine_names()
    failures += _check("Windows engines winrt and sapi offered, mock hidden",
                       "mock" not in names and set(names) >= {"winrt", "sapi"}, f"({names})")
    failures += _check("Windows voices available", eng.available())
    voices = eng.voices()
    per_engine = {n: [v for v in voices if v.id.startswith(n + ":")] for n in names}
    failures += _check("voices listed for every engine",
                       all(per_engine.values()), f"({ {n: len(v) for n, v in per_engine.items()} })")
    failures += _check("each voice is labelled with its engine once, last in the detail",
                       all(v.detail.split(" · ")[-1] == v.id.split(":")[0]
                           and v.detail.count(v.id.split(":")[0]) == 1
                           and v.id.split(":")[0] not in v.name for v in voices),
                       f"({[(v.name, v.detail) for v in voices[:4]]})")
    failures += _check("names drop 'Microsoft' and 'Desktop'",
                       all(not v.name.startswith("Microsoft ") and not v.name.endswith(" Desktop")
                           for v in voices) and any(v.name == "David" for v in voices),
                       f"({[v.name for v in voices]})")
    failures += _check("voice ids unique and stable (engine:full Qt name)",
                       len({v.id for v in voices}) == len(voices)
                       and all(v.id.split(":", 1)[1].startswith("Microsoft") for v in voices),
                       f"({[v.id for v in voices]})")
    failures += _check("detail format", (voice_detail("en_US", "Male", "winrt"),
                                         voice_detail("en_GB", "Unknown", "sapi"))
                       == ("en-US · male · winrt", "en-GB · sapi"))
    failures += _check("speed maps to rate",
                       (speed_to_rate(0.5), speed_to_rate(1.0), speed_to_rate(2.0), speed_to_rate(1.5))
                       == (-1.0, 0.0, 1.0, 0.5))
    for name, listed in per_engine.items():
        if not listed:
            continue
        pick = listed[-1]
        tts = eng.apply(pick.id, 2.0, 0.0)
        failures += _check(f"{name}: voice, rate and volume applied",
                           tts is not None and tts.voice().name() == pick.id.split(":", 1)[1]
                           and abs(tts.rate() - 1.0) < 0.01 and tts.volume() == 0.0,
                           f"({tts.voice().name() if tts else None}, {tts.rate() if tts else None}, "
                           f"{tts.volume() if tts else None})")
        tts = eng.apply(pick.id, 0.5, 0.0)
        failures += _check(f"{name}: slow speed applied", abs(tts.rate() + 1.0) < 0.01)
        states: list = []
        tts.stateChanged.connect(states.append)
        ok = eng.speak("Borase", pick.id, 1.0, 0.0)
        done = _pump_until(lambda t=tts: QTextToSpeech.State.Speaking in states
                           and t.state() == QTextToSpeech.State.Ready, 10)
        failures += _check(f"{name}: speaks at volume 0 to the end",
                           ok and done and tts.volume() == 0.0, f"({[s.name for s in states]})")
        tts.stateChanged.disconnect()
    eng.stop()
    return failures


def check_player() -> int:
    from app.tts.base import Audio
    from app.tts.player import Player

    from PySide6.QtMultimedia import QMediaDevices

    failures = 0
    if QMediaDevices.defaultAudioOutput().isNull():
        return _check("an audio output device exists", False)
    for label, audio, limit in (("PCM tone", _tone(0.3), 5), ("MP3", Audio.mp3(_silent_mp3()), 8)):
        player = Player()
        player.set_volume(0.0)
        events: list[str] = []
        player.started.connect(lambda e=events: e.append("started"))
        player.finished.connect(lambda e=events: e.append("finished"))
        player.failed.connect(lambda msg, e=events: e.append(f"failed {msg}"))
        ok = player.play(audio)
        playing = player.playing() or _pump_until(player.playing, 2)
        done = _pump_until(lambda e=events: "finished" in e or any(x.startswith("failed") for x in e),
                           limit)
        failures += _check(f"Player plays a {label} at volume 0 to completion",
                           ok and playing and done and events == ["started", "finished"]
                           and not player.playing() and player.volume == 0.0,
                           f"({events})")
        player.stop()
    # stop() mid-phrase: no finished signal afterwards.
    player = Player()
    player.set_volume(0.0)
    events = []
    player.finished.connect(lambda: events.append("finished"))
    player.play(_tone(1.0))
    _pump_until(lambda: False, 0.1)
    player.stop()
    _pump_until(lambda: False, 1.2)
    failures += _check("stop() ends playback without finished", events == [] and not player.playing())
    failures += _check("empty audio is refused", player.play(Audio(b"")) is False)
    # stop() mid-MP3, then a Player dropped while its MP3 still plays: no hang, no crash.
    events = []
    player.play(Audio.mp3(_silent_mp3(200)))
    _pump_until(lambda: False, 0.3)
    player.stop()
    _pump_until(lambda: False, 0.5)
    failures += _check("stop() mid-MP3 ends playback without finished",
                       events == [] and not player.playing())
    doomed = Player()
    doomed.set_volume(0.0)
    doomed.play(Audio.mp3(_silent_mp3(200)))
    _pump_until(lambda: False, 0.3)
    del doomed
    alive = _pump_until(lambda: False, 1.0) is False
    failures += _check("a Player deleted mid-MP3 leaves the app running", alive)
    return failures


def main() -> int:
    qt_app = QApplication.instance() or QApplication(sys.argv)
    qt_app.setQuitOnLastWindowClosed(False)
    failures = 0
    for title, fn in (("Phrases", check_phrases), ("Old callers of app.voice", check_old_callers),
                      ("TTS worker", check_worker), ("Windows voices", check_windows_engine),
                      ("Player", check_player), ("Voice facade: fallback", check_facade_fallback),
                      ("Voice facade: synth engines", check_facade_plays)):
        print(title)
        try:
            failures += fn()
        except Exception as exc:        # noqa: BLE001
            import traceback

            traceback.print_exc()
            failures += _check(f"{title} ran", False, f"({type(exc).__name__}: {exc})")
    print("ALL PASS" if not failures else f"{failures} FAILURE(S)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
