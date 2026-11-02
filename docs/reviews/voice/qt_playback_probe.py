"""Check, without playing, that Qt can load our outputs: QSoundEffect (WAV) and QAudioDecoder (MP3)."""
import sys, time
from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer, QUrl
from PySide6.QtMultimedia import QAudioDecoder, QSoundEffect, QMediaDevices
app = QCoreApplication(sys.argv)
wav, mp3 = sys.argv[1], sys.argv[2]
print("default output:", QMediaDevices.defaultAudioOutput().description())
se = QSoundEffect(); loop = QEventLoop()
se.statusChanged.connect(lambda: loop.quit() if se.status() != QSoundEffect.Status.Loading else None)
t = time.perf_counter(); se.setSource(QUrl.fromLocalFile(wav)); QTimer.singleShot(3000, loop.quit); loop.exec()
print("QSoundEffect WAV:", se.status().name, round(time.perf_counter() - t, 3), "s")
dec = QAudioDecoder(); dec.setSource(QUrl.fromLocalFile(mp3)); n = [0, None]; done = QEventLoop()
def rd():
    b = dec.read(); n[0] += b.byteCount(); n[1] = b.format()
dec.bufferReady.connect(rd); dec.finished.connect(done.quit)
dec.error.connect(lambda e: (print("decode error", e, dec.errorString()), done.quit()))
t = time.perf_counter(); dec.start(); QTimer.singleShot(5000, done.quit); done.exec()
f = n[1]
print("QAudioDecoder MP3:", n[0], "bytes PCM", f.sampleRate() if f else None, "Hz", f.sampleFormat().name if f else None, round(time.perf_counter() - t, 3), "s")
