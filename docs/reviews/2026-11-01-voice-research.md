# Free text-to-speech options: research (2026-11-01)

Question (user): a VOICE menu offering every free method side by side, clearly
labelled, to compare and pick. Measured on the user's PC (8 cores, SMT off) at
below-normal priority, ONNX capped at 1-2 threads. Test phrase "Feynmaline,
nineteen deposits" (~2.1 s of audio); times are the median of 5 after a warm-up.
Scripts: `docs/reviews/voice/`. Nothing was installed into the app's venv.

| | Windows voices (Qt winrt / sapi) | Piper (offline neural) | Kokoro (offline neural, kokoro-onnx int8) | Microsoft online (edge-tts) |
|---|---|---|---|---|
| Extra download | none | 34 MB package (trimmable to ~2 MB data) + 60 MB per medium voice | ~10 MB package + 92 MB model + ~0.5 MB per voice | ~1.2 MB package |
| Code licence | LGPL (Qt, already shipped) | **GPL-3.0** (piper-tts, espeak-ng built in) | kokoro-onnx MIT, but **phonemizer GPL-3.0** and espeak-ng GPL-3 | LGPL-3.0 |
| Voice licence | Windows | per voice: public domain / CC0 / CC-BY / CC-BY-SA / non-commercial / research-only | Apache-2.0 | Microsoft service via an unofficial client |
| First load | 0.04-0.14 s | 4.8 s | 1.6-2.5 s | 1.4 s |
| Time to synthesise | plays directly | 0.09 s (2 threads), 0.24 s (1) | 0.74 s (2 threads), 1.1 s (1) | ~0.6 s incl. network |
| Peak CPU (machine %) | ~12 % | 10-18 %, for a fraction of a second | 19 % for ~1 s | ~2 % |
| RAM | small | +118 MB | +166 MB | ~50 MB |
| Network | none | once per voice | once | **every phrase** (text goes to Microsoft) |
| English voices | David, Zira, Mark (winrt); Zira, David (sapi) | 38 | 28 | 47 |
| Conflicts with the app's onnxruntime 1.31 / numpy 2.5 | — | none | none | none |

Notes
- QtTextToSpeech: voice, rate, pitch and volume work on both Windows engines;
  hide the "mock" test engine. PySide6 6.12 does not bind synthesize().
- Playback for Piper/Kokoro: QAudioSink from a QBuffer (Int16 mono); edge-tts
  MP3: QMediaPlayer + QAudioOutput from a QBuffer. All in the shipped PySide6.
- One TTS worker thread at below-normal priority; models loaded once.
- Piper: build the ONNX session ourselves (PiperVoice.load ignores thread
  settings); offer only public-domain / CC0 / CC-BY voices by default.
- edge-tts is unofficial and has broken before when Microsoft changed the
  endpoint; fall back to a Windows voice when it fails.

## Licence finding (needs a decision)
The app is MIT. Piper (piper-tts, espeak-ng) and Kokoro's phonemizer/espeak-ng
are GPL-3.0. Bundling them into the shipped EXE most likely makes that EXE a
GPL-3.0 combined work (MIT code may be combined into GPL; the result is then
distributed under GPL terms, which means offering the source, already public
on GitHub). Not legal advice. Alternatives: download them on demand as an
optional add-on instead of bundling, or leave them out.
