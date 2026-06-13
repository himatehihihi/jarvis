from __future__ import annotations

import queue
import threading
from typing import Optional

import numpy as np
import sounddevice as sd

from . import AudioConfig


class MicrophoneStream:
    def __init__(self, config: AudioConfig):
        self.config = config
        self.sample_queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=256)
        self.stream: Optional[sd.InputStream] = None
        self.running = False
        self.status_text = "stopped"
        self.frames_captured = 0
        self.dropped_frames = 0
        self._lock = threading.Lock()

    def _callback(self, indata, frames, time_info, status):
        if status:
            self.status_text = f"stream_status={status}"
        mono = np.asarray(indata[:, 0], dtype=np.float32).copy()
        with self._lock:
            self.frames_captured += len(mono)
        try:
            self.sample_queue.put_nowait(mono)
        except queue.Full:
            with self._lock:
                self.dropped_frames += 1

    def start(self) -> bool:
        if self.running:
            return True
        blocksize = int(self.config.sample_rate * self.config.block_duration_ms / 1000)
        self.stream = sd.InputStream(
            samplerate=self.config.sample_rate,
            channels=self.config.channels,
            dtype="float32",
            blocksize=blocksize,
            callback=self._callback,
        )
        self.stream.start()
        self.running = True
        self.status_text = "running"
        return True

    def stop(self) -> None:
        if not self.running:
            return
        self.running = False
        if self.stream is not None:
            self.stream.stop()
            self.stream.close()
            self.stream = None
        self.status_text = "stopped"

    def read(self, timeout: float = 0.5) -> Optional[np.ndarray]:
        if not self.running:
            return None
        try:
            return self.sample_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def health(self) -> dict:
        return {
            "running": self.running,
            "status": self.status_text,
            "queue_size": self.sample_queue.qsize(),
            "frames_captured": self.frames_captured,
            "dropped_frames": self.dropped_frames,
        }

