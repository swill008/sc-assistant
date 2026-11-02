"""Text-to-speech engines for the VOICE menu.

Engines are found by id. Each engine module defines a ``base.Engine``
subclass (optionally a module-level ``create()`` returning one); a module
that is missing or fails to import simply leaves that engine out, so the
Windows voices always work.
"""
from __future__ import annotations

import importlib
import logging

from .base import Audio, Engine, EngineError, Voice

__all__ = ["ENGINE_IDS", "Audio", "Engine", "EngineError", "Voice",
           "create_engine", "engine_label"]

log = logging.getLogger(__name__)

# Menu order. Labels live on each engine class; these are the fallbacks used
# when a module cannot be imported.
ENGINE_IDS = ("windows", "piper", "kokoro", "edge")
ENGINE_LABELS = {
    "windows": "Windows voices (built in, offline)",
    "piper": "Piper (offline, natural · add-on, GPL-3.0)",
    "kokoro": "Kokoro (offline, most natural · add-on, GPL-3.0, uses more CPU)",
    "edge": "Microsoft online voices (online: sends the phrase to Microsoft)",
}


def engine_label(engine_id: str) -> str:
    return ENGINE_LABELS.get(engine_id, engine_id)


def create_engine(engine_id: str) -> Engine | None:
    """A new engine for ``engine_id``, or None when its module is missing/broken."""
    if engine_id not in ENGINE_IDS:
        return None
    try:
        module = importlib.import_module(f"{__name__}.{engine_id}")
    except Exception as exc:        # noqa: BLE001 - an add-on must never break the app
        log.warning("TTS engine %s not loaded: %s", engine_id, exc)
        return None
    try:
        factory = getattr(module, "create", None)
        if callable(factory):
            engine = factory()
            if isinstance(engine, Engine):
                return engine
        for value in vars(module).values():
            if (isinstance(value, type) and issubclass(value, Engine)
                    and value is not Engine and getattr(value, "id", "") == engine_id):
                return value()
    except Exception as exc:        # noqa: BLE001
        log.warning("TTS engine %s failed to start: %s", engine_id, exc)
        return None
    log.warning("TTS engine module %s defines no Engine with id %r", engine_id, engine_id)
    return None
