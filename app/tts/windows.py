"""Windows voices through QtTextToSpeech (built in, offline).

Both Windows engines Qt offers, "winrt" and "sapi", are listed side by side;
Qt's "mock" test engine is hidden. A voice id is "<engine>:<voice name>", e.g.
"winrt:Microsoft David". Speaking happens on the GUI thread (QTextToSpeech is
not thread-safe) and needs no worker: Windows plays it itself.
"""
from __future__ import annotations

import logging

from .base import Engine, Voice, clamp_speed

try:
    from PySide6.QtCore import QLocale
    from PySide6.QtTextToSpeech import QTextToSpeech
except Exception:          # Qt built without the Speech module
    QTextToSpeech = None    # type: ignore[assignment,misc]
    QLocale = None          # type: ignore[assignment,misc]

log = logging.getLogger(__name__)

HIDDEN_ENGINES = ("mock",)
PREFERRED_ORDER = ("winrt", "sapi")


def speed_to_rate(speed: float) -> float:
    """Speed 0.5-2.0 to QTextToSpeech rate -1..1 (0.5 -> -1, 1.0 -> 0, 2.0 -> 1)."""
    speed = clamp_speed(speed)
    rate = (speed - 1.0) * 2.0 if speed < 1.0 else speed - 1.0
    return max(-1.0, min(1.0, rate))


def display_name(qt_name: str) -> str:
    """'Microsoft David Desktop' -> 'David' (the id keeps the full name)."""
    name = qt_name.strip()
    if name.startswith("Microsoft "):
        name = name[len("Microsoft "):]
    if name.endswith(" Desktop"):
        name = name[: -len(" Desktop")]
    return name.strip() or qt_name


def voice_detail(locale_name: str, gender: str, engine_name: str) -> str:
    """'en-US · male · winrt': the engine once, last."""
    parts = [locale_name.replace("_", "-")]
    gender = (gender or "").lower()
    if gender and gender != "unknown":
        parts.append(gender)
    parts.append(engine_name)
    return " · ".join(parts)


class WindowsEngine(Engine):
    id = "windows"
    label = "Windows voices (built in, offline)"
    note = "Voices installed in Windows. Nothing is downloaded or sent anywhere."
    speaks_directly = True

    def __init__(self) -> None:
        self._tts: dict[str, object] = {}          # engine name -> QTextToSpeech
        self._voices: dict[str, tuple[object, object]] | None = None  # id -> (QLocale, QVoice)
        self._listed: list[Voice] = []
        self._current: object | None = None        # the QTextToSpeech last used

    # ---- engines ---------------------------------------------------------
    @staticmethod
    def engine_names() -> list[str]:
        """Qt's Windows speech engines, "mock" left out, winrt first."""
        if QTextToSpeech is None:
            return []
        try:
            names = [n for n in QTextToSpeech.availableEngines() if n not in HIDDEN_ENGINES]
        except Exception:       # noqa: BLE001
            return []
        return sorted(names, key=lambda n: (PREFERRED_ORDER.index(n)
                                            if n in PREFERRED_ORDER else len(PREFERRED_ORDER), n))

    def _engine(self, name: str):
        tts = self._tts.get(name)
        if tts is None:
            try:
                tts = QTextToSpeech(name)
            except Exception as exc:        # noqa: BLE001
                log.warning("TTS windows: engine %s failed: %s", name, exc)
                return None
            self._tts[name] = tts
        if tts.state() == QTextToSpeech.State.Error:
            return None
        return tts

    def available(self) -> bool:
        return any(self._engine(n) is not None for n in self.engine_names())

    def unavailable_reason(self) -> str:
        if QTextToSpeech is None:
            return "Qt speech module missing"
        return "" if self.available() else "No speech engine available"

    # ---- voices ----------------------------------------------------------
    def _scan(self) -> None:
        self._voices = {}
        self._listed = []
        english, other = [], []
        for name in self.engine_names():
            tts = self._engine(name)
            if tts is None:
                continue
            original = tts.locale()
            try:
                for loc in tts.availableLocales():
                    tts.setLocale(loc)
                    for qv in tts.availableVoices():
                        vid = f"{name}:{qv.name()}"
                        if vid in self._voices:
                            continue
                        self._voices[vid] = (loc, qv)
                        entry = Voice(vid, display_name(qv.name()),
                                      voice_detail(loc.name(), qv.gender().name, name))
                        (english if loc.language() == QLocale.Language.English else other).append(entry)
            except Exception as exc:        # noqa: BLE001
                log.warning("TTS windows: listing %s voices failed: %s", name, exc)
            finally:
                try:
                    tts.setLocale(original)
                except Exception:       # noqa: BLE001
                    pass
        self._listed = english + other

    def voices(self) -> list[Voice]:
        if self._voices is None:
            self._scan()
        return list(self._listed)

    def default_voice(self) -> str:
        return ""        # Windows' own default voice

    # ---- speaking --------------------------------------------------------
    def _pick(self, voice_id: str):
        """(QTextToSpeech, QVoice or None) for ``voice_id``; '' = first engine's default."""
        engine_name, _, _voice_name = (voice_id or "").partition(":")
        if voice_id:
            if self._voices is None:
                self._scan()
            found = (self._voices or {}).get(voice_id)
            tts = self._engine(engine_name) if found else None
            if tts is not None:
                return tts, found
        for name in self.engine_names():
            tts = self._engine(name)
            if tts is not None:
                return tts, None
        return None, None

    def apply(self, voice_id: str, speed: float, volume: float):
        """Set voice, rate and volume on the engine for ``voice_id``; returns it."""
        tts, found = self._pick(voice_id)
        if tts is None:
            return None
        if found is not None:
            loc, qv = found
            if tts.locale() != loc:
                tts.setLocale(loc)
            tts.setVoice(qv)
        tts.setRate(speed_to_rate(speed))
        tts.setVolume(max(0.0, min(1.0, float(volume))))
        return tts

    def speak(self, text: str, voice_id: str, speed: float, volume: float) -> bool:
        self.stop()
        tts = self.apply(voice_id, speed, volume)
        if tts is None:
            return False
        self._current = tts
        tts.say(text)
        return True

    def set_volume(self, volume: float) -> None:
        if self._current is not None:
            self._current.setVolume(max(0.0, min(1.0, float(volume))))

    def stop(self) -> None:
        for tts in self._tts.values():
            try:
                if tts.state() in (QTextToSpeech.State.Speaking, QTextToSpeech.State.Synthesizing,
                                   QTextToSpeech.State.Paused):
                    tts.stop()
            except Exception:       # noqa: BLE001
                pass

    def speaking(self) -> bool:
        return any(tts.state() == QTextToSpeech.State.Speaking for tts in self._tts.values())
