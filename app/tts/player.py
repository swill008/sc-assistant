"""Plays synthesised speech on the GUI thread, straight from memory.

PCM (Piper, Kokoro) goes through QAudioSink reading a QBuffer; MP3 (Microsoft
online voices) through QMediaPlayer + QAudioOutput reading a QBuffer (Qt's
FFmpeg backend, shipped with PySide6, decodes it). No temp files.
"""
from __future__ import annotations

import logging

import shiboken6

from PySide6 import QtMultimedia as _qtm
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QObject, QTimer, QUrl, Signal
from PySide6.QtMultimedia import (QAudioFormat, QAudioOutput, QAudioSink,
                                  QMediaDevices, QMediaPlayer)

from .base import FLOAT32, Audio

# QAudioSink reports QtAudio enums (Qt 6.7+); comparing them with the old
# QAudio names is always unequal.
QAudio = getattr(_qtm, "QtAudio", None) or _qtm.QAudio

log = logging.getLogger(__name__)

# MP3 players still alive (see Player._play_mp3); removed when Qt deletes them.
_LIVE_MEDIA: set = set()


def _dispose_media(media: QMediaPlayer) -> None:
    """Stop an MP3 player and delete it (with its QAudioOutput and QBuffer)."""
    if not shiboken6.isValid(media):
        _LIVE_MEDIA.discard(media)
        return
    media.blockSignals(True)
    media.stop()
    media.deleteLater()


class Player(QObject):
    """One phrase at a time; ``play`` replaces what is playing."""

    started = Signal()
    finished = Signal()          # played to the end (not after stop())
    failed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._volume = 0.8
        self._sink: QAudioSink | None = None
        self._buffer: QBuffer | None = None
        self._media: QMediaPlayer | None = None
        self._output: QAudioOutput | None = None
        self._poll = QTimer(self)
        self._poll.setInterval(20)
        self._poll.timeout.connect(self._check_sink)
        self._mp3_playing = False      # the current MP3 has not finished / failed / stopped

    # ------------------------------------------------------------------
    @property
    def volume(self) -> float:
        return self._volume

    def set_volume(self, value: float) -> None:
        self._volume = max(0.0, min(1.0, float(value)))
        if self._sink is not None:
            self._sink.setVolume(self._volume)
        if self._output is not None:
            self._output.setVolume(self._volume)

    def playing(self) -> bool:
        if self._sink is not None and self._sink.state() == QAudio.State.ActiveState:
            return True
        return self._mp3_playing

    def play(self, audio: Audio) -> bool:
        """Start playing ``audio``; False when it cannot be played at all."""
        self.stop()
        if audio is None or not audio.data:
            return False
        try:
            return self._play_mp3(audio.data) if audio.is_mp3 else self._play_pcm(audio)
        except Exception as exc:        # noqa: BLE001
            log.warning("TTS player: %s", exc)
            self.stop()
            return False

    # ---- PCM -------------------------------------------------------------
    def _play_pcm(self, audio: Audio) -> bool:
        fmt = QAudioFormat()
        fmt.setSampleRate(int(audio.sample_rate))
        fmt.setChannelCount(int(audio.channels))
        fmt.setSampleFormat(QAudioFormat.SampleFormat.Float
                            if audio.sample_format == FLOAT32 else QAudioFormat.SampleFormat.Int16)
        device = QMediaDevices.defaultAudioOutput()
        if device.isNull():
            self.failed.emit("no audio output device")
            return False
        buf = QBuffer(self)
        buf.setData(QByteArray(audio.data))
        buf.open(QIODevice.OpenModeFlag.ReadOnly)
        sink = QAudioSink(device, fmt, self)
        sink.setVolume(self._volume)
        # Polled, not stateChanged: PySide 6.12 cannot pass QAudio::State to
        # any Python slot ("cannot be converted").
        self._poll.start()
        self._buffer, self._sink = buf, sink
        sink.start(buf)
        if sink.error() != QAudio.Error.NoError:
            self.failed.emit(f"audio sink: {sink.error().name}")
            self.stop()
            return False
        self.started.emit()
        return True

    def _check_sink(self) -> None:
        sink = self._sink
        if sink is None:
            self._poll.stop()
            return
        state = sink.state()
        if state == QAudio.State.IdleState:          # buffer played out
            self._drop_sink()
            self.finished.emit()
        elif state == QAudio.State.StoppedState and sink.error() != QAudio.Error.NoError:
            error = sink.error().name
            self._drop_sink()
            self.failed.emit(f"audio sink: {error}")

    def _drop_sink(self) -> None:
        sink = self._sink
        if sink is None:
            return
        buf = self._buffer
        self._sink = self._buffer = None
        self._poll.stop()
        if sink is not None:
            sink.stop()
            sink.deleteLater()
        if buf is not None:
            buf.close()
            buf.deleteLater()

    # ---- MP3 -------------------------------------------------------------
    # Each MP3 gets its own QMediaPlayer + QAudioOutput, with the QBuffer as
    # their child, and is stopped and deleted when done. Measured with Qt's
    # FFmpeg backend (PySide6 6.12): setSourceDevice(None) soon after
    # EndOfMedia, and stop() inside the player's own status signal, hang the
    # GUI thread; stop() + deleteLater() from the event loop do not.
    def _play_mp3(self, data: bytes) -> bool:
        # No parent: deleting a Player must never delete a QMediaPlayer whose
        # FFmpeg threads are still running (that aborts the process); each
        # one is kept in _LIVE_MEDIA until its own deferred delete.
        media = QMediaPlayer()
        _LIVE_MEDIA.add(media)
        media.destroyed.connect(lambda _obj=None, m=media: _LIVE_MEDIA.discard(m))
        output = QAudioOutput(media)
        output.setVolume(self._volume)
        media.setAudioOutput(output)
        buf = QBuffer(media)
        buf.setData(QByteArray(data))
        buf.open(QIODevice.OpenModeFlag.ReadOnly)
        media.mediaStatusChanged.connect(lambda status, m=media: self._on_media_status(m, status))
        media.errorOccurred.connect(lambda error, msg, m=media: self._on_media_error(m, error, msg))
        self._media, self._output, self._mp3_playing = media, output, True
        media.setSourceDevice(buf, QUrl("speech.mp3"))
        media.play()
        self.started.emit()
        return True

    def _on_media_status(self, media: QMediaPlayer, status) -> None:
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self._mp3_done(media, None)
        elif status == QMediaPlayer.MediaStatus.InvalidMedia:
            self._mp3_done(media, "could not decode the audio")

    def _on_media_error(self, media: QMediaPlayer, error, message: str = "") -> None:
        if error != QMediaPlayer.Error.NoError:
            self._mp3_done(media, message or error.name)

    def _mp3_done(self, media: QMediaPlayer, error: str | None) -> None:
        if media is not self._media or not self._mp3_playing:
            return                      # stopped, replaced or already reported
        self._mp3_playing = False
        self._media = self._output = None
        QTimer.singleShot(0, lambda m=media: _dispose_media(m))
        if error is None:
            self.finished.emit()
        else:
            self.failed.emit(error)

    # ------------------------------------------------------------------
    def stop(self) -> None:
        self._drop_sink()
        media = self._media
        if media is None:
            return
        self._media = self._output = None
        self._mp3_playing = False
        # Deferred: stop() may be called from a slot of the player's own signal.
        media.blockSignals(True)
        QTimer.singleShot(0, lambda m=media: _dispose_media(m))

    def __del__(self) -> None:
        # Hand a still-playing MP3 over to the event loop instead of letting
        # it go with this object.
        media = self.__dict__.get("_media")
        if media is not None and shiboken6.isValid(media):
            media.blockSignals(True)
            QTimer.singleShot(0, lambda m=media: _dispose_media(m))
