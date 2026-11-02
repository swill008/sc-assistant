"""Spoken ore announcements: the facade over the VOICE menu's engines.

``Voice`` keeps the original API (``say``, ``set_enabled``, ``set_volume``,
``available``, ``stop``) and adds the menu's choices: engine, voice, speed and
what-it-says style. The Windows voices (QtTextToSpeech) speak on the GUI
thread; the other engines synthesise on one below-normal TTS worker thread and
the audio plays through ``app.tts.player.Player``. When the chosen engine is
missing, still needs a download, or fails, the phrase is spoken by a Windows
voice instead and a warning is logged (and sent through ``notice``).

Announcements are made by the controller only when a *new* signature locks, so
a rock that stays on screen is spoken once, not four times a second.
"""
from __future__ import annotations

import logging
import re

from PySide6.QtCore import QObject, Signal

from .tts import ENGINE_IDS, create_engine, engine_label
from .tts.base import Audio, Engine, clamp_speed
from .tts.base import Voice as VoiceInfo
from .tts.phrases import DEFAULT_STYLE, STYLES, test_phrase
from .tts.phrases import spoken_text as _phrase

log = logging.getLogger(__name__)

__all__ = ["Voice", "VoiceInfo", "spoken_text"]


def spoken_text(label: str, count: int = 1, value: int | float | None = None,
                style: str = DEFAULT_STYLE, unit: str = "rocks") -> str:
    """'Borase', 3 -> 'Borase, times 3' (see app.tts.phrases for the styles)."""
    return _phrase(label, count, value, style, unit)


def _clean(text: str) -> str:
    return re.sub(r"[^\w\s,.'\-]", " ", str(text or "")).strip()


class Voice(QObject):
    """One voice for the whole app."""

    # A one-line warning for the menu's note line (fallbacks, failures).
    notice = Signal(str)

    def __init__(self, engine: str = "windows", voice: str = "", speed: float = 1.0,
                 style: str = DEFAULT_STYLE, volume: float = 0.8,
                 enabled: bool = True, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._enabled = bool(enabled)
        self._volume = max(0.0, min(1.0, float(volume)))
        self._speed = clamp_speed(speed)
        self._style = style if style in STYLES else DEFAULT_STYLE
        self._engine_id = engine if engine in ENGINE_IDS else "windows"
        self._voice_id = str(voice or "")
        self._engines: dict[str, Engine | None] = {}
        self._worker = None          # app.tts.worker.TtsWorker, made on first use
        self._player = None          # app.tts.player.Player, made on first use
        self._pending: dict[int, str] = {}   # worker job -> text (for fallback)
        self.last_error = ""

    # ---- engines ---------------------------------------------------------
    def engine(self, engine_id: str | None = None) -> Engine | None:
        """The engine object for ``engine_id`` (default: the chosen one)."""
        engine_id = engine_id or self._engine_id
        if engine_id not in self._engines:
            self._engines[engine_id] = create_engine(engine_id)
        return self._engines[engine_id]

    def engines(self) -> list[tuple[str, str]]:
        """(id, label) for every engine in menu order, loadable or not."""
        out = []
        for engine_id in ENGINE_IDS:
            eng = self.engine(engine_id)
            out.append((engine_id, (eng.label if eng and eng.label else engine_label(engine_id))))
        return out

    def voices(self, engine_id: str | None = None) -> list[VoiceInfo]:
        eng = self.engine(engine_id)
        if eng is None:
            return []
        try:
            return list(eng.voices())
        except Exception as exc:        # noqa: BLE001
            log.warning("TTS %s: listing voices failed: %s", eng.id, exc)
            return []

    def _windows(self) -> Engine | None:
        return self.engine("windows")

    # ---- settings --------------------------------------------------------
    @property
    def engine_id(self) -> str:
        return self._engine_id

    def set_engine(self, engine_id: str) -> None:
        if engine_id not in ENGINE_IDS:
            return
        if engine_id != self._engine_id:
            self.stop()
            self._engine_id = engine_id

    @property
    def voice_id(self) -> str:
        return self._voice_id

    def set_voice(self, voice_id: str) -> None:
        self._voice_id = str(voice_id or "")

    @property
    def speed(self) -> float:
        return self._speed

    def set_speed(self, speed: float) -> None:
        """0.5-2.0 (1.0 = normal)."""
        self._speed = clamp_speed(speed)

    @property
    def style(self) -> str:
        return self._style

    def set_style(self, style: str) -> None:
        if style in STYLES:
            self._style = style

    @property
    def available(self) -> bool:
        """Can anything be spoken (the Windows voices are the fallback)?"""
        win = self._windows()
        if win is not None and win.available():
            return True
        eng = self.engine()
        return bool(eng is not None and self._engine_id != "windows" and self._ready(eng))

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)
        if not self._enabled:
            self.stop()

    @property
    def volume(self) -> float:
        return self._volume

    def set_volume(self, value: float) -> None:
        """0.0 - 1.0, applied to whatever is speaking now."""
        self._volume = max(0.0, min(1.0, float(value)))
        if self._player is not None:
            self._player.set_volume(self._volume)
        win = self._engines.get("windows")
        if win is not None and hasattr(win, "set_volume"):
            try:
                win.set_volume(self._volume)
            except Exception:       # noqa: BLE001
                pass

    # ---- speaking --------------------------------------------------------
    def phrase(self, label: str, count: int = 1, value: int | float | None = None,
               unit: str = "rocks") -> str:
        """The announcement for a reading in the chosen style."""
        return _phrase(label, count, value, self._style, unit)

    def test(self) -> bool:
        """Say the TEST phrase with the current settings (even when voice is off)."""
        return self._say(test_phrase(self._style), force=True)

    def say(self, text: str) -> bool:
        """Speak one short phrase, replacing anything still being spoken."""
        return self._say(text, force=False)

    def _say(self, text: str, force: bool) -> bool:
        if not ((self._enabled or force) and text):
            return False
        cleaned = _clean(text)
        if not cleaned:
            return False
        self.stop()
        eng = self.engine()
        if eng is None:
            return self._fallback(cleaned, f"{engine_label(self._engine_id)} is not installed")
        if eng.speaks_directly:
            return self._speak_windows(cleaned, self._voice_id)
        if not self._ready(eng):
            reason = eng.unavailable_reason() or "not ready"
            try:
                if eng.available() and eng.needs_download(self._voice_id or eng.default_voice()):
                    reason = "the voice is not downloaded yet"
            except Exception:       # noqa: BLE001
                pass
            return self._fallback(cleaned, f"{eng.label or eng.id}: {reason}")
        worker = self._ensure_worker()
        job = worker.submit(eng, cleaned, self._voice_id or eng.default_voice(), self._speed)
        self._pending = {job: cleaned}
        return True

    def _ready(self, eng: Engine) -> bool:
        try:
            if not eng.available():
                return False
            return eng.needs_download(self._voice_id or eng.default_voice()) == 0
        except Exception as exc:        # noqa: BLE001
            log.warning("TTS %s: readiness check failed: %s", eng.id, exc)
            return False

    def _speak_windows(self, text: str, voice_id: str) -> bool:
        win = self._windows()
        if win is None or not win.available():
            return False
        try:
            return bool(win.speak(text, voice_id, self._speed, self._volume))
        except Exception as exc:        # noqa: BLE001
            log.warning("TTS windows: speak failed: %s", exc)
            return False

    def _fallback(self, text: str, reason: str) -> bool:
        """Say ``text`` with a Windows voice because the chosen engine can't."""
        self.last_error = reason
        log.warning("TTS fallback to Windows voices: %s", reason)
        self.notice.emit(f"{reason}; using a Windows voice")
        # The chosen voice id belongs to another engine: use the Windows default.
        return self._speak_windows(text, "")

    def _ensure_worker(self):
        if self._worker is None:
            from .tts.worker import TtsWorker
            self._worker = TtsWorker(self)
            self._worker.audio_ready.connect(self._on_audio)
            self._worker.failed.connect(self._on_failed)
            self._worker.start_worker()
        return self._worker

    def _ensure_player(self):
        if self._player is None:
            from .tts.player import Player
            self._player = Player(self)
            self._player.set_volume(self._volume)
            self._player.failed.connect(self._on_play_failed)
        return self._player

    def _on_audio(self, audio: Audio, job: int) -> None:
        if job not in self._pending:
            return                      # stopped or replaced meanwhile
        text = self._pending.pop(job)
        if not self._ensure_player().play(audio):
            self._fallback(text, "playback failed")

    def _on_failed(self, error: str, job: int) -> None:
        text = self._pending.pop(job, None)
        if text is not None:
            self._fallback(text, f"{engine_label(self._engine_id)} failed: {error}")

    def _on_play_failed(self, error: str) -> None:
        self.last_error = f"playback failed: {error}"
        log.warning("TTS %s", self.last_error)
        self.notice.emit(self.last_error)

    def stop(self) -> None:
        self._pending = {}
        if self._worker is not None:
            self._worker.cancel()
        if self._player is not None:
            self._player.stop()
        for eng in self._engines.values():
            if eng is not None and eng.speaks_directly:
                try:
                    eng.stop()
                except Exception:       # noqa: BLE001
                    pass

    def shutdown(self) -> None:
        """Stop speaking and end the worker thread (call when the app quits)."""
        self.stop()
        if self._worker is not None:
            self._worker.shutdown()
            self._worker = None
