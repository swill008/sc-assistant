"""Microsoft online voices through edge-tts.

Every phrase is sent to Microsoft's speech service, so the menu labels this
engine "online". edge-tts is an unofficial client and has broken before when
Microsoft changed the endpoint: every failure here raises ``EdgeError`` with a
short reason, and the Voice facade falls back to a Windows voice.

``synth`` and ``refresh_voices`` block (they run an asyncio loop of their own),
so call them on the TTS worker thread, never the GUI thread. ``voices()`` only
reads the cache (memory, then the file under %LOCALAPPDATA%), falling back to a
short built-in list, so it is safe anywhere.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
import os
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Protocol

from app.tts import base

log = logging.getLogger(__name__)

ENGINE_ID = "edge"
LABEL = "Microsoft online voices (online: sends the phrase to Microsoft)"
DEFAULT_VOICE = "en-US-AriaNeural"

CONNECT_TIMEOUT = 5         # seconds to open the socket
RECEIVE_TIMEOUT = 8         # seconds between chunks
SYNTH_TIMEOUT = 12.0        # whole phrase
LIST_TIMEOUT = 8.0          # voice list

# Shown until the online list has been fetched once (offline first start).
FALLBACK_VOICES: tuple[tuple[str, str], ...] = (
    ("en-US-AriaNeural", "Female"),
    ("en-US-GuyNeural", "Male"),
    ("en-US-JennyNeural", "Female"),
    ("en-US-AndrewNeural", "Male"),
    ("en-US-EmmaNeural", "Female"),
    ("en-US-BrianNeural", "Male"),
    ("en-GB-SoniaNeural", "Female"),
    ("en-GB-RyanNeural", "Male"),
)


class EdgeError(base.EngineError):
    """edge-tts failed; the message says why (no network, timeout, ...)."""


def rate_string(speed: float) -> str:
    """Speed multiplier (0.5-2.0) as edge-tts's rate, e.g. 1.25 -> "+25%"."""
    return f"{round((base.clamp_speed(speed) - 1.0) * 100):+d}%"


def _voice_name(short_name: str) -> str:
    """"en-GB-RyanNeural" -> "Ryan (en-GB)"."""
    parts = short_name.split("-", 2)
    if len(parts) == 3:
        name = parts[2].removesuffix("Neural")
        name = name.replace("Multilingual", " multilingual")
        return f"{name} ({parts[0]}-{parts[1]})"
    return short_name


def _to_voices(raw: list[dict]) -> list[base.Voice]:
    out: list[base.Voice] = []
    for v in raw:
        sn = str(v.get("ShortName", ""))
        if not sn.startswith("en-"):
            continue
        tags = v.get("VoiceTag") or {}
        traits = ", ".join(tags.get("VoicePersonalities") or [])
        detail = str(v.get("Gender", ""))
        if traits:
            detail = f"{detail} · {traits}" if detail else traits
        out.append(base.Voice(sn, _voice_name(sn), detail))
    out.sort(key=lambda x: (not x.id.startswith(("en-US-", "en-GB-")), x.id))
    return out


# ---- transport: the only part that touches the network --------------------
class Transport(Protocol):
    async def list_voices(self) -> list[dict]: ...

    def stream(self, text: str, voice: str, rate: str) -> AsyncIterator[bytes]: ...


class EdgeTransport:
    """The real edge-tts calls."""

    async def list_voices(self) -> list[dict]:
        import edge_tts
        return list(await edge_tts.list_voices())

    async def stream(self, text: str, voice: str, rate: str) -> AsyncIterator[bytes]:
        import edge_tts
        com = edge_tts.Communicate(text, voice, rate=rate,
                                   connect_timeout=CONNECT_TIMEOUT,
                                   receive_timeout=RECEIVE_TIMEOUT)
        async for chunk in com.stream():
            if chunk.get("type") == "audio" and chunk.get("data"):
                yield chunk["data"]


def edge_tts_installed() -> bool:
    """edge-tts can be imported (checked without importing aiohttp yet)."""
    try:
        return importlib.util.find_spec("edge_tts") is not None
    except (ImportError, ValueError):
        return False


def _cache_file() -> Path | None:
    root = os.environ.get("LOCALAPPDATA")
    if not root:
        return None
    return Path(root) / "SC Assistant" / "voices" / ENGINE_ID / "voices.json"


def _run(coro_factory: Callable[[], object], timeout: float, what: str):
    """Run one coroutine on a fresh loop on this (worker) thread."""
    async def guarded():
        return await asyncio.wait_for(coro_factory(), timeout)  # type: ignore[arg-type]
    try:
        return asyncio.run(guarded())
    except (TimeoutError, asyncio.TimeoutError):
        raise EdgeError(f"{what}: no answer from Microsoft within {timeout:g} s") from None
    except EdgeError:
        raise
    except Exception as exc:     # aiohttp / edge-tts errors: no network, endpoint changed
        raise EdgeError(f"{what}: {type(exc).__name__}: {exc}".rstrip(": ")) from exc


class EdgeEngine(base.Engine):
    id = ENGINE_ID
    label = LABEL
    note = "Online: every phrase is sent to Microsoft. Falls back to a Windows voice when it fails."
    online = True

    def __init__(self, transport: Transport | None = None,
                 synth_timeout: float = SYNTH_TIMEOUT,
                 list_timeout: float = LIST_TIMEOUT) -> None:
        self._transport = transport
        self._synth_timeout = synth_timeout
        self._list_timeout = list_timeout
        self._voices: list[base.Voice] | None = None

    # ---- base.Engine ------------------------------------------------------
    def available(self) -> bool:
        return self._transport is not None or edge_tts_installed()

    def unavailable_reason(self) -> str:
        return "" if self.available() else "edge-tts is not installed"

    def default_voice(self) -> str:
        return DEFAULT_VOICE

    def voices(self) -> list[base.Voice]:
        """Cached English voices; never touches the network."""
        if self._voices is None:
            self._voices = self._read_cache()
        if self._voices:
            return list(self._voices)
        return [base.Voice(sn, _voice_name(sn), g) for sn, g in FALLBACK_VOICES]

    def synth(self, text: str, voice_id: str, speed: float) -> base.Audio | None:
        """MP3 audio for ``text`` (worker thread); raises EdgeError on failure."""
        text = (text or "").strip()
        if not text:
            return None
        voice = voice_id or DEFAULT_VOICE
        rate = rate_string(speed)
        transport = self._get_transport()

        async def collect() -> bytes:
            buf = bytearray()
            async for data in transport.stream(text, voice, rate):
                buf += data
            return bytes(buf)

        audio = _run(collect, self._synth_timeout, "Microsoft voice")
        if not audio:
            raise EdgeError("Microsoft voice: no audio received")
        return base.Audio.mp3(audio)

    # ---- voice list -------------------------------------------------------
    def refresh_voices(self) -> list[base.Voice]:
        """Fetch the online list (blocking; worker thread) and cache it."""
        transport = self._get_transport()
        raw = _run(transport.list_voices, self._list_timeout, "Microsoft voice list")
        voices = _to_voices(raw)
        if not voices:
            raise EdgeError("Microsoft voice list: no English voices in the answer")
        self._voices = voices
        self._write_cache(voices)
        return list(voices)

    # ---- internals --------------------------------------------------------
    def _get_transport(self) -> Transport:
        if self._transport is None:
            if not edge_tts_installed():
                raise EdgeError("Microsoft voice: edge-tts is not installed")
            self._transport = EdgeTransport()
        return self._transport

    @staticmethod
    def _read_cache() -> list[base.Voice]:
        path = _cache_file()
        if path is None:
            return []
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
            return [base.Voice(str(r["id"]), str(r["name"]), str(r.get("detail", "")))
                    for r in rows]
        except FileNotFoundError:
            return []
        except Exception as exc:
            log.warning("Microsoft voice list cache unreadable (%s); using the built-in list", exc)
            return []

    @staticmethod
    def _write_cache(voices: list[base.Voice]) -> None:
        path = _cache_file()
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps([{"id": v.id, "name": v.name, "detail": v.detail}
                                       for v in voices], indent=1), encoding="utf-8")
            os.replace(tmp, path)
        except OSError as exc:
            log.warning("Could not save the Microsoft voice list: %s", exc)
