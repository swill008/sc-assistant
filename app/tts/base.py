"""What every speech engine offers (the VOICE menu lists them side by side).

An engine either turns text into audio (``synth``: Piper, Kokoro, Microsoft
online) that ``app.tts.player.Player`` plays, or speaks directly (``speak``:
the Windows voices). ``synth`` runs on the TTS worker thread, never on the
GUI thread; ``speak`` runs on the GUI thread.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

# ONNX engines run on this many threads (research: 1 is enough, 2 optional).
ONNX_THREADS = 1

# Sample formats an Audio can carry.
INT16 = "int16"
FLOAT32 = "float32"
MP3 = "mp3"


@dataclass(frozen=True)
class Voice:
    """One voice an engine offers. ``id`` is what the config stores."""

    id: str
    name: str
    detail: str = ""        # e.g. "winrt · en-US", "CC0 · 60 MB", "female, US"


@dataclass(frozen=True)
class Audio:
    """Synthesised speech: raw PCM, or MP3 bytes (``sample_format == "mp3"``).

    PCM is interleaved little-endian; ``sample_rate``/``channels`` are ignored
    for MP3.
    """

    data: bytes
    sample_rate: int = 22050
    channels: int = 1
    sample_format: str = INT16          # INT16 | FLOAT32 | MP3

    @classmethod
    def mp3(cls, data: bytes) -> Audio:
        return cls(bytes(data), 0, 0, MP3)

    @property
    def is_mp3(self) -> bool:
        return self.sample_format == MP3

    @property
    def seconds(self) -> float:
        """Length of PCM audio (0.0 for MP3, which has no fixed rate here)."""
        if self.is_mp3 or not self.sample_rate or not self.channels:
            return 0.0
        width = 4 if self.sample_format == FLOAT32 else 2
        return len(self.data) / (width * self.channels * self.sample_rate)


class EngineError(RuntimeError):
    """An engine could not do what was asked (missing add-on, network, model)."""


class Cancelled(Exception):
    """A download was cancelled by the user."""


Progress = Callable[[int, int], None]     # (bytes got, bytes total; total 0 = unknown)
CancelCheck = Callable[[], bool]


class Engine:
    """Base class. Subclasses set ``id``/``label`` and override what they support.

    ``id`` is one of "windows", "piper", "kokoro", "edge" (fixed: the config
    stores it). ``note`` is the grey line under the menu (licence, online).
    """

    id: str = ""
    label: str = ""
    note: str = ""
    # True for engines that send text over the network (shown in the menu).
    online: bool = False
    # True when the engine speaks itself (Windows) instead of returning Audio.
    speaks_directly: bool = False

    def available(self) -> bool:
        """Can this engine run on this PC now (add-on present, Qt module there)?"""
        return False

    def unavailable_reason(self) -> str:
        """One short line for the menu when ``available()`` is False."""
        return ""

    def voices(self) -> list[Voice]:
        return []

    def default_voice(self) -> str:
        found = self.voices()
        return found[0].id if found else ""

    def needs_download(self, voice_id: str) -> int:
        """Bytes still to download before ``voice_id`` can speak (0 = ready)."""
        return 0

    def download(self, voice_id: str, progress: Progress | None = None,
                 cancelled: CancelCheck | None = None) -> None:
        """Fetch what ``voice_id`` needs. Raises Cancelled or EngineError."""
        return None

    def synth(self, text: str, voice_id: str, speed: float) -> Audio | None:
        """Text to audio, on the worker thread. Raises EngineError on failure."""
        raise EngineError(f"{self.id or 'engine'} cannot synthesise")

    def speak(self, text: str, voice_id: str, speed: float, volume: float) -> bool:
        """Speak directly (only engines with ``speaks_directly``)."""
        return False

    def stop(self) -> None:
        """Stop speaking (engines that speak directly)."""
        return None


def clamp_speed(speed: float) -> float:
    """Speed setting 0.5-2.0 (1.0 = normal)."""
    try:
        value = float(speed)
    except (TypeError, ValueError):
        return 1.0
    if value != value:          # NaN
        return 1.0
    return max(0.5, min(2.0, value))
