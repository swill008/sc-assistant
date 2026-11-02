"""Kokoro: the most natural offline voices (optional add-on, GPL-3.0).

kokoro-onnx is MIT, but it needs phonemizer and espeak-ng (GPL-3.0), so the
whole engine is an on-demand add-on (see ``app.tts.addons``). The model is the
int8 export from onnx-community/Kokoro-82M-v1.0-ONNX (92 MB) and each voice is
its own 0.5 MB file, both pinned by revision and sha256. Kokoro's model and
voices are Apache-2.0.

Nothing from the add-on is imported until the first phrase; the ONNX session
runs on one thread with no idle spinning.
"""
from __future__ import annotations

import importlib
import logging
import threading
from typing import Any

from app.tts import addons, base

log = logging.getLogger(__name__)

ENGINE_ID = "kokoro"
LABEL = "Kokoro (offline, most natural · add-on, GPL-3.0, uses more CPU)"
REVISION = "1939ad2a8e416c0acfeecc08a694d14ef25f2231"
BASE_URL = f"https://huggingface.co/onnx-community/Kokoro-82M-v1.0-ONNX/resolve/{REVISION}/"
SAMPLE_RATE = 24000
DEFAULT_VOICE = "am_michael"
EMPTY_VOICES = "no-voices.npz"     # kokoro-onnx insists on a voices file; ours come one by one

MODEL = addons.RemoteFile(BASE_URL + "onnx/model_quantized.onnx", "kokoro-v1.0-int8.onnx",
                          92361116, "fbae9257e1e05ffc727e951ef9b9c98418e6d79f1c9b6b13bd59f5c9028a1478")

# English voices: name -> (bytes, sha256) of voices/<name>.bin at REVISION.
KOKORO_VOICES: dict[str, tuple[int, str]] = {
    "af_alloy": (522240, "c4a6b876047fd7fb472edf4ebd63cfac7c3b958a7cae7c106e8f038ca6308c45"),
    "af_aoede": (522240, "4a004c33430762e2461eedb2013fad808ef4ab3121f5300f554476caf58d8361"),
    "af_bella": (522240, "f69d836209b78eb8c66e75e3cda491e26ea838a3674257e9d4e5703cbaf55c8b"),
    "af_heart": (522240, "d583ccff3cdca2f7fae535cb998ac07e9fcb90f09737b9a41fa2734ec44a8f0b"),
    "af_jessica": (522240, "a240a5e3c15b43563d6e923bdca8ef5613a23471d9b77653694012435df23bd8"),
    "af_kore": (522240, "9be5221b6a941c04b561959b8ff0b06e809444dcc4ab7e75a7b23606f691819e"),
    "af_nicole": (522240, "cd2191ab31b914ed7b318416b0e4440fdf392ddad9106a060819aa600a64f59a"),
    "af_nova": (522240, "18778272caa0d0eebaea251c35fd635f038434f9eee5e691d02a174bd328414f"),
    "af_river": (522240, "00a2bcf82b1d86e8f19902ede58c65ccf6c0e43b44b7d74fad54e5d8933c9c30"),
    "af_sarah": (522240, "4409fbc125afabacc615d94db5398d847006a737b0247d6892b7a9a0007a2f0a"),
    "af_sky": (522240, "4435255c9744f3f31659e0d714ab7689bf65d9e77ec1cce060f083912614f0b9"),
    "am_adam": (522240, "162b035ed91cfc48b6046982184c645f72edcdd1b82843347f605d7bf7b15716"),
    "am_echo": (522240, "3968b92c3c4cd1c4416dbded36c13eaa388a90d5788d02a13e4d781f5f8cf3c3"),
    "am_eric": (522240, "e8b5be17edd1e3636901ce7598baafe2dc8dd8ff707a0c23bf9e461add7e2832"),
    "am_fenrir": (522240, "c27989f741f7ee34d273a39d8a595cc0837d35f5ced9a29b7cc162614616df43"),
    "am_liam": (522240, "52403be32fd047c6a44517cb0bcd6b134f2a18baa73e70ef41651e0eab921ade"),
    "am_michael": (522240, "1d1f21dd8da39c30705cd4c75d039d265e9bc4a2a93ed09bc9e1b1225eb95ba1"),
    "am_onyx": (522240, "da5d135b424164916d75a68ffb4c2abce3d7d5ccc82dd1ee6cf447ce286145e6"),
    "am_puck": (522240, "fcf73c989033e9233e0b98713eca600c8c74dcc1614b37009d5450ff4a2274a0"),
    "am_santa": (522240, "61150cf726ab6c5ed7a99f90a304f91f5a72c00c592e89ec94e5df11c319227a"),
    "bf_alice": (522240, "08afa6ba24da61ea5e8efa139e5aadc938d83f0a6da5a900adaf763ac1da5573"),
    "bf_emma": (522240, "669fe0647f9dd04fcab92f1439a40eeb4c8b4ab1f82e4996fe3d918ce4a63b73"),
    "bf_isabella": (522240, "3754352c4aaa46d17f27654ab7518d65b62ad6163a0f55a5f4330c2da2c4e94f"),
    "bf_lily": (522240, "5e0ee32ebe64a467124976b14e69590746f1c4ce41a12b587a50c862edfea335"),
    "bm_daniel": (522240, "6b3194bbceffb746733cbc22c8f593dd44e401a71d53895a2dca891bc595a1e8"),
    "bm_fable": (522240, "f889083196807b4adb15e9204252165f503b8d33d3982e681c52443c49d798f1"),
    "bm_george": (522240, "c4b235a4c1f2cd3b939fed08b899ce9385638b763f7b73a59616c4fc9bd6c9bc"),
    "bm_lewis": (522240, "b8f671cef828c30e66fdf0b0756a76bba58f6bb3398cbbf27058642acbcedb97"),
}

_ACCENT = {"a": ("US", "en-us"), "b": ("GB", "en-gb")}
_GENDER = {"f": "female", "m": "male"}


def voice_file(name: str) -> addons.RemoteFile:
    size, sha = KOKORO_VOICES[name]
    return addons.RemoteFile(BASE_URL + f"voices/{name}.bin", f"{name}.bin", size, sha)


def _files(name: str) -> tuple[addons.RemoteFile, ...]:
    return (MODEL, voice_file(name))


class KokoroEngine(base.Engine):
    id = ENGINE_ID
    label = LABEL
    note = ("Add-on, GPL-3.0 (phonemizer, espeak-ng; kokoro-onnx is MIT), downloaded on "
            "first use. Model and voices Apache-2.0. Uses more CPU than Piper.")

    def __init__(self, threads: int = base.ONNX_THREADS) -> None:
        self._threads = threads
        self._kokoro: Any = None
        self._styles: dict[str, Any] = {}
        self._lock = threading.Lock()

    # ---- base.Engine ------------------------------------------------------
    def available(self) -> bool:
        return addons.installed(ENGINE_ID)

    def unavailable_reason(self) -> str:
        if self.available():
            return ""
        need = addons.package_bytes(ENGINE_ID) + MODEL.size
        return f"Add-on not downloaded yet ({addons.size_text(need)}, GPL-3.0)"

    def default_voice(self) -> str:
        return DEFAULT_VOICE

    def voices(self) -> list[base.Voice]:
        out = []
        for name in sorted(KOKORO_VOICES):
            accent = _ACCENT[name[0]][0]
            gender = _GENDER[name[1]]
            size = addons.size_text(KOKORO_VOICES[name][0])
            out.append(base.Voice(name, f"{name[3:].title()} ({accent}, {gender})",
                                  f"Apache-2.0 · {size}"))
        return out

    def needs_download(self, voice_id: str) -> int:
        return addons.missing_bytes(ENGINE_ID, _files(self._name(voice_id)))

    def download(self, voice_id: str, progress: base.Progress | None = None,
                 cancelled: base.CancelCheck | None = None) -> None:
        files = _files(self._name(voice_id))
        pkg = addons.package_bytes(ENGINE_ID)
        total = addons.missing_bytes(ENGINE_ID, files)

        def scaled(offset: int) -> base.Progress | None:
            if progress is None:
                return None
            return lambda got, _t: progress(min(total, offset + got), total)

        addons.install(ENGINE_ID, progress=scaled(0), cancelled=cancelled)
        addons.fetch_files(ENGINE_ID, files, progress=scaled(pkg), cancelled=cancelled)

    def synth(self, text: str, voice_id: str, speed: float) -> base.Audio | None:
        text = (text or "").strip()
        if not text:
            return None
        name = self._name(voice_id)
        kokoro, style, np = self._load(name)
        try:
            samples, rate = kokoro.create(text, voice=style, speed=base.clamp_speed(speed),
                                          lang=_ACCENT[name[0]][1])
            pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2").tobytes()
        except Exception as exc:        # noqa: BLE001 - phonemizer/onnx errors
            raise base.EngineError(f"Kokoro: {type(exc).__name__}: {exc}") from exc
        if not pcm:
            raise base.EngineError("Kokoro: no audio for the phrase")
        return base.Audio(pcm, int(rate or SAMPLE_RATE), 1, base.INT16)

    # ---- helpers ----------------------------------------------------------
    @staticmethod
    def _name(voice_id: str) -> str:
        name = voice_id or DEFAULT_VOICE
        if name not in KOKORO_VOICES:
            raise base.EngineError(f"Kokoro: voice {name!r} is not offered")
        return name

    def _load(self, name: str):
        with self._lock:
            import numpy as np
            if addons.missing_bytes(ENGINE_ID, _files(name)):
                raise base.EngineError(f"Kokoro: voice {name} is not downloaded")
            folder = addons.voices_dir(ENGINE_ID)
            if self._kokoro is None:
                addons.activate(ENGINE_ID)
                try:
                    kokoro_onnx = importlib.import_module("kokoro_onnx")
                    empty = folder / EMPTY_VOICES
                    if not empty.is_file():
                        np.savez(empty)
                    session = addons.onnx_session(folder / MODEL.name, self._threads)
                    self._kokoro = kokoro_onnx.Kokoro.from_session(session, str(empty))
                except Exception as exc:    # noqa: BLE001 - broken add-on or model
                    raise base.EngineError(f"Kokoro: cannot load the model: {exc}") from exc
                log.info("Kokoro model loaded")
            if name not in self._styles:
                try:
                    raw = np.fromfile(folder / f"{name}.bin", dtype="<f4")
                    self._styles[name] = raw.reshape(-1, 1, 256)
                except (OSError, ValueError) as exc:
                    raise base.EngineError(f"Kokoro: voice {name} unreadable: {exc}") from exc
            return self._kokoro, self._styles[name], np


def create() -> KokoroEngine:
    return KokoroEngine()
