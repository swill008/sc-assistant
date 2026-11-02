"""Piper: offline neural voices (optional add-on, GPL-3.0).

The piper-tts package and the chosen voice are downloaded on demand (see
``app.tts.addons``); nothing is bundled into the EXE and nothing from piper is
imported until the first phrase. The ONNX session is built here, on one
thread with no idle spinning, because ``PiperVoice.load`` ignores thread
settings.

Only voices whose dataset licence is public domain, CC0 or CC-BY are offered.
The catalogue below was taken from voices.json and each voice's MODEL_CARD at
a pinned revision of huggingface.co/rhasspy/piper-voices.
"""
from __future__ import annotations

import importlib
import json
import logging
import threading
from dataclasses import dataclass
from typing import Any

from app.tts import addons, base

log = logging.getLogger(__name__)

ENGINE_ID = "piper"
LABEL = "Piper (offline, natural · add-on, GPL-3.0)"
REVISION = "b4e358ffcb232591bf73a540e70f7de528e4174a"
BASE_URL = f"https://huggingface.co/rhasspy/piper-voices/resolve/{REVISION}/"
DEFAULT_VOICE = "en_US-joe-medium"


@dataclass(frozen=True)
class PiperVoiceInfo:
    key: str            # e.g. "en_US-joe-medium"
    licence: str        # dataset licence from MODEL_CARD
    speakers: int
    onnx_size: int
    onnx_sha256: str
    json_size: int
    json_sha256: str

    @property
    def path(self) -> str:
        """Folder in the repo, e.g. en/en_US/joe/medium/."""
        lang, name, quality = self.key.split("-", 2)
        return f"{lang.split('_')[0]}/{lang}/{name}/{quality}/"

    @property
    def size(self) -> int:
        return self.onnx_size + self.json_size

    def files(self) -> tuple[addons.RemoteFile, ...]:
        url = BASE_URL + self.path + self.key
        return (addons.RemoteFile(url + ".onnx", self.key + ".onnx",
                                  self.onnx_size, self.onnx_sha256),
                addons.RemoteFile(url + ".onnx.json", self.key + ".onnx.json",
                                  self.json_size, self.json_sha256))


def _pv(key: str, licence: str, speakers: int, onnx_size: int, onnx_sha: str,
        json_size: int, json_sha: str) -> PiperVoiceInfo:
    return PiperVoiceInfo(key, licence, speakers, onnx_size, onnx_sha, json_size, json_sha)


_BAD = ("nc", "sa", "nd", "noncommercial", "sharealike", "noderivs")


def licence_allowed(text: str) -> bool:
    """Public domain, CC0 or plain CC-BY; never NC/SA/ND, research-only or unknown."""
    t = " ".join((text or "").lower().split())
    if not t:
        return False
    if t in ("public domain", "cc0", "cc0 1.0", "cc0-1.0") or "publicdomain/zero" in t:
        return True
    url = "creativecommons.org/licenses/"
    if url in t:
        kind = t.split(url, 1)[1].split("/", 1)[0]          # "by", "by-nc-sa", ...
    elif t.startswith(("cc-by", "cc by")):
        kind = t[3:].split(" 4")[0].split(" 3")[0].replace(" ", "-")
    else:
        return False
    parts = kind.split("-")
    return parts[0] == "by" and not any(p in _BAD for p in parts[1:])


# English voices at REVISION whose MODEL_CARD licence passes licence_allowed.
# Left out: lessac, amy, alan, danny, kusal, jenny_dioco, arctic ("see URL",
# Blizzard or unknown terms), ryan, hfc_*, semaine, l2arctic (non-commercial),
# northern/southern_english_* (share-alike), sam (Apache-2.0, not in the set).
PIPER_VOICES: tuple[PiperVoiceInfo, ...] = (
    _pv("en_GB-alba-medium", "CC-BY-4.0", 1,
        63201294, "401369c4a81d09fdd86c32c5c864440811dbdcc66466cde2d64f7133a66ad03b",
        4888, "aa965a2f02ecced632c2694e1fc72bbff6d65f265fab567ca945918c73dd89f4"),
    _pv("en_GB-aru-medium", "CC-BY-4.0", 12,
        76754097, "9e74d089a8563f8b2446426d01becb046cd3c3bfbafe1a20fd03a9a79bd82619",
        5048, "00529fabf0e79f29a9cb10fda5b60f9b7cf80671faac2b316e13af20e7816d5e"),
    _pv("en_GB-cori-high", "public domain", 1,
        114219352, "470b4dd634c98f8a4850d7626ffc3dfc90774628eeef6605a6dd8f88f30a5903",
        4963, "9e7fb5b5671612c22f3c81cbe46c1ae87b031a4632bcb509e499dad6f1e2adec"),
    _pv("en_GB-cori-medium", "public domain", 1,
        63531379, "1899f98e5fb8310154f3c2973f4b8a929ba7245e722b3d3a85680b833d95f10d",
        4966, "e262c16d7f192f69d4edd6b4ef8a5915379e67495fcc402f1ab15eeb33da3d36"),
    _pv("en_GB-vctk-medium", "CC-BY-4.0", 109,
        76952753, "4e9fc85ab9009385319fc6bae7f55577f8a2d7ee77fd9159a5500eb6531f41e6",
        6637, "7f85e6391ed0f7f46e4abd19345929a16be931a0c9945086f96692dce2087fa8"),
    _pv("en_US-bryce-medium", "public domain", 1,
        63531379, "dc9caa6c313199ffb5ac698b6e542fa6cba388aeaf2731e25262e33b9810aef1",
        4966, "7ceb1bc4af6d4e41b6d1edbb86c67e91e01eaa71f66db4cd0ae92ac704d415be"),
    _pv("en_US-joe-medium", "CC0", 1,
        63201294, "58afce0321b8d9c46d7cdf9c16500cc55a793b4220212dba6b70fb788b3baf06",
        4794, "3d6d5410b3795cb1950595247ef8f06190719e6fdbfa3a2356d8ec368e1aad33"),
    _pv("en_US-john-medium", "public domain", 1,
        63531379, "789c6c875726e627ddee93d51d8727859abe9c091c3d141591f4b83c2072e988",
        4965, "af60f177b6b550f3d7a302720c0fb89e7f94a82b5dca464775ef63b1c69ba09a"),
    _pv("en_US-kathleen-low", "CC0", 1,
        63104526, "87adf17f5326bc0782282147a8b9788406236245f0f9b0e68dacb651bc1de8b6",
        4169, "39ebab88416edce0f63781754651788620cb97b9bb73ddf3c01f28e29a648feb"),
    _pv("en_US-kristin-medium", "public domain", 1,
        63531379, "5849957f929cbf720c258f8458692d6103fff2f0e3d3b19c8259474bb06a18d4",
        4968, "5681426d4aead22195de70531eeeeddb46493cfaffc5764b2ea3db73428b651c"),
    _pv("en_US-libritts-high", "CC-BY-4.0", 904,
        136673811, "9127a559e11603f10b366d1a20ac7426826081dbc521de4c2420c57728d73f0f",
        20163, "2efdc6d7f954588b8180132cbd9b8001933fdd00932c92bc92fd0d2028a9eb3d"),
    _pv("en_US-libritts_r-medium", "CC-BY-4.0", 2306,
        78580914, "10bb85e071d616fcf4071f369f1799d0491492ab3c5d552ec19fb548fac13195",
        20123, "b471dc60d2d8335e819c393d196d6fbf792817f40051257b269878505bc9afb3"),
    _pv("en_US-ljspeech-high", "public domain", 1,
        114199011, "5d4f08ba6a2a48c44592eed3ce56bf85e9de3dd4e20df90541ae68a8310c029a",
        4970, "7e1f4634af596d83cca997fb7a931ba80b70f8a316a2655ee69c55365e0ace14"),
    _pv("en_US-ljspeech-medium", "public domain", 1,
        63531379, "6f52a751e2349abe7a76735eb09dc1875298c77ea2342ffd2fef79ff81b87f22",
        4972, "141d612cc0a95ed7efc1ca936b845c2364967f2e9217c5dbfcf69fc4d6c65860"),
    _pv("en_US-mike-medium", "CC0", 1,
        63221984, "3157e69e2c580cab297483f4b301ee975a4590c17d35a9757e33347d0e90fae2",
        5439, "0a2538c0b1e06a6cab7c46b97c79abd5e6a34a6c05b74b9376874c7099d81dad"),
    _pv("en_US-norman-medium", "public domain", 1,
        63531379, "b9739443232a80a59c7d18810dd856899bf16a7964725f5ab81ea49b1351cb71",
        4968, "6c2db7f558a4a8deb9fe822583c1c5105f6c4e834dd0f9de8ad17a888ee9fe1d"),
    _pv("en_US-reza_ibrahim-medium", "CC0", 1,
        63511038, "99f0c31464a2120831ca87d079e10a9a2b3e426cc1ee662d80ff9042df15cd3c",
        4976, "465ddf1702917fe617b7d69ed81301d6a2f39f083a754bd1cf6db8955d09a381"),
)


def catalogue(voices: tuple[PiperVoiceInfo, ...] = PIPER_VOICES) -> tuple[PiperVoiceInfo, ...]:
    """The voices the menu may offer (licence-filtered)."""
    return tuple(v for v in voices if licence_allowed(v.licence))


class PiperEngine(base.Engine):
    id = ENGINE_ID
    label = LABEL
    note = ("Add-on, GPL-3.0 (piper-tts, espeak-ng), downloaded on first use. Voices: "
            "public domain, CC0 or CC-BY 4.0 (credit: the dataset authors listed on "
            "huggingface.co/rhasspy/piper-voices).")

    def __init__(self, voices: tuple[PiperVoiceInfo, ...] | None = None,
                 threads: int = base.ONNX_THREADS) -> None:
        self._voices = catalogue(PIPER_VOICES if voices is None else voices)
        self._threads = threads
        self._loaded: dict[str, Any] = {}       # voice key -> PiperVoice (one at a time)
        self._lock = threading.Lock()

    # ---- base.Engine ------------------------------------------------------
    def available(self) -> bool:
        return addons.installed(ENGINE_ID)

    def unavailable_reason(self) -> str:
        if self.available():
            return ""
        return (f"Add-on not downloaded yet "
                f"({addons.size_text(addons.package_bytes(ENGINE_ID))}, GPL-3.0)")

    def default_voice(self) -> str:
        keys = [v.key for v in self._voices]
        return DEFAULT_VOICE if DEFAULT_VOICE in keys else (keys[0] if keys else "")

    def voices(self) -> list[base.Voice]:
        out = []
        for v in self._voices:
            lang, name, quality = v.key.split("-", 2)
            ready = addons.missing_bytes(ENGINE_ID, v.files()) == addons.package_bytes(ENGINE_ID)
            speakers = f" · {v.speakers} speakers" if v.speakers > 1 else ""
            size = "downloaded" if ready else addons.size_text(v.size)
            out.append(base.Voice(
                v.key, f"{name.replace('_', ' ').title()} ({lang[-2:]}, {quality})",
                f"{v.licence}{speakers} · {size}"))
        return out

    def needs_download(self, voice_id: str) -> int:
        return addons.missing_bytes(ENGINE_ID, self._info(voice_id).files())

    def download(self, voice_id: str, progress: base.Progress | None = None,
                 cancelled: base.CancelCheck | None = None) -> None:
        files = self._info(voice_id).files()
        pkg = addons.package_bytes(ENGINE_ID)
        total = addons.missing_bytes(ENGINE_ID, files)
        addons.install(ENGINE_ID, progress=_scaled(progress, 0, total), cancelled=cancelled)
        addons.fetch_files(ENGINE_ID, files, progress=_scaled(progress, pkg, total),
                           cancelled=cancelled)

    def synth(self, text: str, voice_id: str, speed: float) -> base.Audio | None:
        text = (text or "").strip()
        if not text:
            return None
        voice = self._load(voice_id or self.default_voice())
        try:
            piper_config = importlib.import_module("piper.config")
            syn = piper_config.SynthesisConfig(
                length_scale=float(voice.config.length_scale) / base.clamp_speed(speed))
            pcm = b"".join(c.audio_int16_bytes for c in voice.synthesize(text, syn_config=syn))
        except Exception as exc:        # noqa: BLE001 - espeak/onnx errors
            raise base.EngineError(f"Piper: {type(exc).__name__}: {exc}") from exc
        if not pcm:
            raise base.EngineError("Piper: no audio for the phrase")
        return base.Audio(pcm, int(voice.config.sample_rate), 1, base.INT16)

    # ---- helpers ----------------------------------------------------------
    def _info(self, voice_id: str) -> PiperVoiceInfo:
        key = voice_id or self.default_voice()
        for v in self._voices:
            if v.key == key:
                return v
        raise base.EngineError(f"Piper: voice {key!r} is not offered")

    def _load(self, voice_id: str):
        with self._lock:
            if voice_id in self._loaded:
                return self._loaded[voice_id]
            info = self._info(voice_id)
            if addons.missing_bytes(ENGINE_ID, info.files()):
                raise base.EngineError(f"Piper: voice {voice_id} is not downloaded")
            addons.activate(ENGINE_ID)
            folder = addons.voices_dir(ENGINE_ID)
            try:
                piper_config = importlib.import_module("piper.config")
                piper_voice = importlib.import_module("piper.voice")
                model = folder / (info.key + ".onnx")
                with open(folder / (info.key + ".onnx.json"), encoding="utf-8") as f:
                    cfg = piper_config.PiperConfig.from_dict(json.load(f))
                voice = piper_voice.PiperVoice(
                    session=addons.onnx_session(model, self._threads), config=cfg,
                    download_dir=folder, use_tashkeel=False)
            except Exception as exc:    # noqa: BLE001 - broken add-on or model
                raise base.EngineError(f"Piper: cannot load {voice_id}: {exc}") from exc
            self._loaded = {voice_id: voice}
            log.info("Piper voice %s loaded", voice_id)
            return voice


def _scaled(progress: base.Progress | None, offset: int, total: int) -> base.Progress | None:
    """Report one step's bytes as part of one bar over ``total`` bytes."""
    if progress is None:
        return None

    def report(got: int, _step_total: int) -> None:
        progress(min(total, offset + got), total)
    return report


def create() -> PiperEngine:
    return PiperEngine()
