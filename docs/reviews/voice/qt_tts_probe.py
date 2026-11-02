"""List QtTextToSpeech engines/voices/capabilities and time synthesize() (no playback).

Run with the app's own interpreter (read-only use): PYTHONDONTWRITEBYTECODE=1 python -I qt_tts_probe.py <wav_dir>
"""
import json
import os
import statistics
import sys
import threading
import time
import wave

import psutil
from PySide6.QtCore import QCoreApplication, QEventLoop, QLocale, QTimer, qVersion
from PySide6.QtTextToSpeech import QTextToSpeech

PHRASE = "Feynmaline, nineteen deposits"
proc = psutil.Process()
proc.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
app = QCoreApplication(sys.argv)
wavs = sys.argv[1]
report = {"qt": qVersion(), "engines": {}}

for eng in QTextToSpeech.availableEngines():
    t0 = time.perf_counter()
    tts = QTextToSpeech(eng)
    loop = QEventLoop()
    if tts.state() != QTextToSpeech.State.Ready:
        tts.stateChanged.connect(lambda s: loop.quit())
        QTimer.singleShot(5000, loop.quit)
        loop.exec()
    info = {"init_s": round(time.perf_counter() - t0, 3), "state": tts.state().name}
    caps = tts.engineCapabilities()
    info["capabilities"] = [c.name for c in QTextToSpeech.Capability if c != QTextToSpeech.Capability.None_ and caps & c]
    voices = []
    for loc in tts.availableLocales():
        if loc.language() != QLocale.Language.English:
            continue
        tts.setLocale(loc)
        for v in tts.availableVoices():
            voices.append(f"{v.name()} ({loc.name()}, {v.gender().name})")
    info["english_voices"] = voices
    tts.setRate(0.3)
    tts.setPitch(-0.2)
    tts.setVolume(0.8)
    info["rate_pitch_volume_after_set"] = [round(tts.rate(), 2), round(tts.pitch(), 2), round(tts.volume(), 2)]
    tts.setRate(0.0)
    tts.setPitch(0.0)

    # PySide6 does not bind synthesize(); time say() at volume 0 (silent):
    # latency to Speaking and total time to Ready, plus peak CPU.
    tts.setVolume(0.0)
    lat, tot, peaks = [], [], []
    for i in range(6):
        marks = {}
        done = QEventLoop()

        def on_state(s, d=done, m=marks):
            if s == QTextToSpeech.State.Speaking and "speak" not in m:
                m["speak"] = time.perf_counter()
            elif s == QTextToSpeech.State.Ready and "speak" in m:
                m["ready"] = time.perf_counter()
                d.quit()
        conn = tts.stateChanged.connect(on_state)
        peak = [0.0]
        stop = threading.Event()

        def sample():
            proc.cpu_percent(None)
            while not stop.wait(0.05):
                peak[0] = max(peak[0], proc.cpu_percent(None))
        th = threading.Thread(target=sample, daemon=True)
        th.start()
        ts = time.perf_counter()
        tts.say(PHRASE)
        QTimer.singleShot(10000, done.quit)
        done.exec()
        stop.set()
        th.join()
        tts.stateChanged.disconnect(conn)
        if i and "ready" in marks:
            lat.append(marks["speak"] - ts)
            tot.append(marks["ready"] - ts)
            peaks.append(peak[0])
    if lat:
        info["say_to_speaking_median_s"] = round(statistics.median(lat), 3)
        info["say_to_done_median_s"] = round(statistics.median(tot), 3)
        info["peak_cpu_pct_of_one_core"] = round(max(peaks), 1)
    report["engines"][eng] = info
    del tts

print(json.dumps(report, indent=1))
