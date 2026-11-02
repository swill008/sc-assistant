"""Measure one TTS method: load time, synth time (median of 5), peak CPU.

Usage: python -I bench.py <method> <threads> <models_dir> <wav_dir> [variant]
method: piper | kokoro | edge
Runs itself at BELOW_NORMAL priority. Prints one JSON line.
"""
import json
import os
import statistics
import sys
import threading
import time
import wave

import psutil

PHRASE = "Feynmaline, nineteen deposits"

proc = psutil.Process()
proc.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
NCPU = psutil.cpu_count(logical=True)


class CpuSampler:
    """Samples this process' CPU use every 50 ms; peak in % of one core."""

    def __init__(self):
        self.peak = 0.0
        self.samples = []
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        proc.cpu_percent(None)
        while not self._stop.wait(0.05):
            v = proc.cpu_percent(None)
            self.samples.append(v)
            self.peak = max(self.peak, v)

    def __enter__(self):
        self._t.start()
        return self

    def __exit__(self, *a):
        self._stop.set()
        self._t.join()


def write_wav(path, pcm16: bytes, rate: int):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm16)


def main():
    method, threads, models, wavs = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]
    variant = sys.argv[5] if len(sys.argv) > 5 else ""
    out = {"method": method, "variant": variant, "threads": threads}
    rss0 = proc.memory_info().rss

    t0 = time.perf_counter()
    if method in ("piper", "kokoro"):
        import onnxruntime as ort
        so = ort.SessionOptions()
        so.intra_op_num_threads = threads
        so.inter_op_num_threads = 1
        so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        # Spinning worker threads burn CPU while idle; turn it off.
        so.add_session_config_entry("session.intra_op.allow_spinning", "0")
    out["import_s"] = round(time.perf_counter() - t0, 3)

    t0 = time.perf_counter()
    if method == "piper":
        from piper.config import PiperConfig, SynthesisConfig
        from piper.voice import PiperVoice
        model = os.path.join(models, "piper", "en_US-lessac-medium.onnx")
        with open(model + ".json", encoding="utf-8") as f:
            cfg = PiperConfig.from_dict(json.load(f))
        voice = PiperVoice(
            session=ort.InferenceSession(model, sess_options=so, providers=["CPUExecutionProvider"]),
            config=cfg,
        )
        rate = cfg.sample_rate

        def synth():
            return b"".join(c.audio_int16_bytes for c in voice.synthesize(PHRASE))
    elif method == "kokoro":
        import numpy as np
        from kokoro_onnx import Kokoro
        mfile = variant or "kokoro-v1.0.onnx"
        model = os.path.join(models, "kokoro", mfile)
        sess = ort.InferenceSession(model, sess_options=so, providers=["CPUExecutionProvider"])
        kok = Kokoro.from_session(sess, os.path.join(models, "kokoro", "voices-v1.0.bin"))
        out["voices"] = kok.get_voices()

        def synth():
            samples, sr = kok.create(PHRASE, voice="am_michael", speed=1.0, lang="en-us")
            synth.rate = sr
            return (np.clip(samples, -1, 1) * 32767).astype(np.int16).tobytes()
        rate = 24000
    elif method == "edge":
        import asyncio
        import edge_tts

        def synth():
            async def go():
                c = edge_tts.Communicate(PHRASE, "en-US-GuyNeural")
                buf = bytearray()
                first = None
                ts = time.perf_counter()
                async for chunk in c.stream():
                    if chunk["type"] == "audio":
                        if first is None:
                            first = time.perf_counter() - ts
                        buf += chunk["data"]
                synth.first = first
                return bytes(buf)
            return asyncio.run(go())
        rate = None
    else:
        raise SystemExit("unknown method")
    out["load_s"] = round(time.perf_counter() - t0, 3)
    out["rss_after_load_mb"] = round((proc.memory_info().rss - rss0) / 2**20, 1)

    times, peaks, firsts, means = [], [], [], []
    audio = b""
    for i in range(6):  # first run is warm-up, reported separately
        with CpuSampler() as s:
            ts = time.perf_counter()
            audio = synth()
            dt = time.perf_counter() - ts
        if i == 0:
            out["first_synth_s"] = round(dt, 3)
            continue
        times.append(dt)
        peaks.append(s.peak)
        if s.samples:
            means.append(statistics.mean(s.samples))
        if method == "edge":
            firsts.append(synth.first)
    out["synth_median_s"] = round(statistics.median(times), 3)
    out["synth_all_s"] = [round(t, 3) for t in times]
    out["peak_cpu_pct_of_one_core"] = round(max(peaks), 1)
    out["peak_cpu_pct_of_machine"] = round(max(peaks) / NCPU, 1)
    out["mean_cpu_pct_of_one_core"] = round(statistics.mean(means), 1) if means else None
    out["rss_peak_mb"] = round(proc.memory_info().rss / 2**20, 1)
    if method == "edge":
        out["first_audio_median_s"] = round(statistics.median(firsts), 3)
        path = os.path.join(wavs, "edge_GuyNeural.mp3")
        with open(path, "wb") as f:
            f.write(audio)
        out["output"] = "MP3 (24 kHz mono 48 kbit/s)"
    else:
        rate = getattr(synth, "rate", rate)
        name = f"{method}_{(variant or 'default').replace('.onnx', '')}_t{threads}.wav"
        path = os.path.join(wavs, name)
        write_wav(path, audio, rate)
        out["audio_s"] = round(len(audio) / 2 / rate, 2)
        out["rtf"] = round(out["synth_median_s"] / out["audio_s"], 3)
        out["output"] = f"PCM16 mono {rate} Hz"
    out["file"] = os.path.basename(path)
    out["file_bytes"] = os.path.getsize(path)
    out.pop("voices", None) if method != "kokoro" else None
    print(json.dumps(out))


if __name__ == "__main__":
    main()
