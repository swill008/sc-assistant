"""The TTS worker thread: synthesises off the GUI thread, newest phrase wins.

One ``TtsWorker`` per app, at below-normal priority. ``submit`` never blocks:
it replaces whatever was waiting, and a phrase that finishes after a newer one
was submitted (or after ``cancel``) is dropped, so the voice never lags behind
the scanner. Audio is sent to the GUI thread through ``audio_ready``. Engines
keep their loaded models between phrases (loaded once per engine/voice).

``DownloadThread`` runs one engine download (add-on or voice) with progress
and cancel, also at below-normal priority.
"""
from __future__ import annotations

import logging
import threading

from PySide6.QtCore import QObject, QThread, Signal

from .base import Cancelled, Engine

log = logging.getLogger(__name__)

# Qt maps LowPriority to THREAD_PRIORITY_BELOW_NORMAL on Windows.
PRIORITY = QThread.Priority.LowPriority
_IDLE_WAIT_S = 0.5           # bounded waits: the loop re-checks for shutdown
SHUTDOWN_WAIT_MS = 5000


class TtsWorker(QThread):
    audio_ready = Signal(object, int)      # (base.Audio, job id)
    failed = Signal(str, int)              # (error, job id)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("tts-worker")
        self._cond = threading.Condition()
        self._job: tuple[int, Engine, str, str, float] | None = None
        self._latest = 0          # newest job id handed out (cancel bumps it too)
        self._next = 0
        self._quit = False
        self.dropped = 0          # stale phrases thrown away (for tests / debug)
        self.synthesised = 0

    def start_worker(self) -> None:
        if not self.isRunning():
            self.start(PRIORITY)

    def submit(self, engine: Engine, text: str, voice_id: str, speed: float) -> int:
        """Queue one phrase, replacing any phrase still waiting; returns its job id."""
        with self._cond:
            self._next += 1
            job = self._next
            if self._job is not None:
                self.dropped += 1
            self._latest = job
            self._job = (job, engine, text, voice_id, speed)
            self._cond.notify()
        return job

    def cancel(self) -> None:
        """Drop the waiting phrase and the result of the one being made."""
        with self._cond:
            if self._job is not None:
                self.dropped += 1
            self._job = None
            self._next += 1
            self._latest = self._next

    def shutdown(self) -> None:
        with self._cond:
            self._quit = True
            self._job = None
            self._cond.notify()
        if self.isRunning() and not self.wait(SHUTDOWN_WAIT_MS):
            log.warning("TTS worker did not stop within %d ms", SHUTDOWN_WAIT_MS)

    def run(self) -> None:
        while True:
            with self._cond:
                while self._job is None and not self._quit:
                    self._cond.wait(_IDLE_WAIT_S)
                if self._quit:
                    return
                job, engine, text, voice_id, speed = self._job
                self._job = None
            try:
                audio = engine.synth(text, voice_id, speed)
                error = "" if audio is not None else "no audio"
            except Exception as exc:        # noqa: BLE001 - reported, then fall back
                audio, error = None, str(exc) or type(exc).__name__
                log.warning("TTS %s synth failed: %s", getattr(engine, "id", "?"), error)
            with self._cond:
                stale = job != self._latest or self._quit
                if stale:
                    self.dropped += 1
                elif audio is not None:
                    self.synthesised += 1
            if stale:
                continue
            if audio is not None:
                self.audio_ready.emit(audio, job)
            else:
                self.failed.emit(error, job)


class DownloadThread(QThread):
    """``engine.download(voice_id)`` off the GUI thread."""

    progress = Signal(object, object)  # bytes got, bytes total (0 = unknown); ints, may pass 2 GB
    done = Signal()
    cancelled = Signal()
    failed = Signal(str)

    def __init__(self, engine: Engine, voice_id: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.setObjectName(f"tts-download-{getattr(engine, 'id', '')}")
        self.engine = engine
        self.voice_id = voice_id
        self._cancel = threading.Event()

    def begin(self) -> None:
        self.start(PRIORITY)

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        try:
            self.engine.download(self.voice_id,
                                 lambda got, total: self.progress.emit(int(got), int(total or 0)),
                                 self._cancel.is_set)
        except Cancelled:
            self.cancelled.emit()
            return
        except Exception as exc:        # noqa: BLE001
            self.failed.emit(str(exc) or type(exc).__name__)
            return
        if self._cancel.is_set():
            self.cancelled.emit()
        else:
            self.done.emit()
