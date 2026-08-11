from __future__ import annotations

import queue
import threading
from typing import Optional

import numpy as np
import sounddevice as sd


class GeminiAudioSpeaker:
    """Interruptible PCM speaker playback for Gemini Live audio output."""

    def __init__(self, sample_rate: int = 24000):
        self.sample_rate = sample_rate
        self.queue: queue.Queue[bytes] = queue.Queue(maxsize=256)
        self.running = False
        self.playing = False
        self.thread: Optional[threading.Thread] = None
        self.last_error = ""
        self.interruptions = 0
        self._playback_lock = threading.Lock()
        self._interrupt_requested = threading.Event()

    def start(self) -> None:
        if self.running:
            return
        self.running = True
        self._interrupt_requested.clear()
        self.thread = threading.Thread(target=self._loop, daemon=True, name="jarvis-gemini-speaker")
        self.thread.start()

    def stop(self) -> None:
        self.running = False
        self.interrupt()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=3)

    def play(self, pcm16le_audio: bytes) -> None:
        if not pcm16le_audio:
            return
        try:
            self.queue.put_nowait(pcm16le_audio)
        except queue.Full:
            pass

    def interrupt(self) -> None:
        self._interrupt_requested.set()
        self.clear()
        try:
            sd.stop()
        except Exception:
            pass
        self.interruptions += 1

    def clear(self) -> int:
        cleared = 0
        while True:
            try:
                self.queue.get_nowait()
                cleared += 1
            except queue.Empty:
                break
        return cleared

    def is_playing(self) -> bool:
        return self.playing or not self.queue.empty()

    def health(self) -> dict:
        return {
            "running": self.running,
            "playing": self.playing,
            "queued_chunks": self.queue.qsize(),
            "interruptions": self.interruptions,
            "last_error": self.last_error,
        }

    def _loop(self) -> None:
        while self.running:
            try:
                chunk = self.queue.get(timeout=0.2)
            except queue.Empty:
                continue
            if not chunk:
                continue
            try:
                from core import runtime

                with self._playback_lock:
                    self.playing = True
                    self._interrupt_requested.clear()
                    runtime.set_speaking(True)
                    samples = np.frombuffer(chunk, dtype=np.int16).astype(np.float32) / 32768.0
                    if samples.size:
                        sd.play(samples, samplerate=self.sample_rate, blocking=True)
            except Exception as exc:
                self.last_error = str(exc)
            finally:
                try:
                    from core import runtime

                    runtime.set_speaking(False)
                    runtime.suppress_input(0.05)
                except Exception:
                    pass
                self.playing = False
