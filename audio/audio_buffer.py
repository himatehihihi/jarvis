from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Deque, List

import numpy as np

from . import AudioConfig


@dataclass
class CaptureSession:
    active: bool = False
    post_roll_remaining: int = 0


class RollingAudioBuffer:
    def __init__(self, config: AudioConfig):
        self.config = config
        self.pre_roll_samples = int(config.pre_roll_s * config.sample_rate)
        self.post_roll_samples = int(config.post_roll_s * config.sample_rate)
        self.ring: Deque[float] = deque(maxlen=max(self.pre_roll_samples, config.sample_rate))
        self.session = CaptureSession()
        self._captured: List[np.ndarray] = []

    def push(self, frame: np.ndarray) -> None:
        self.ring.extend(frame.tolist())
        if self.session.active:
            self._captured.append(frame.copy())

    def start_capture(self) -> None:
        pre = np.asarray(self.ring, dtype=np.float32)
        if pre.size > self.pre_roll_samples:
            pre = pre[-self.pre_roll_samples :]
        self._captured = [pre] if pre.size else []
        self.session.active = True
        self.session.post_roll_remaining = self.post_roll_samples

    def stop_speech_and_collect_post_roll(self, frame_len: int) -> bool:
        if not self.session.active:
            return False
        self.session.post_roll_remaining -= frame_len
        return self.session.post_roll_remaining <= 0

    def finalize_capture(self) -> np.ndarray:
        self.session.active = False
        self.session.post_roll_remaining = 0
        if not self._captured:
            return np.array([], dtype=np.float32)
        out = np.concatenate(self._captured).astype(np.float32)
        self._captured = []
        return out

    def captured_duration_s(self) -> float:
        if not self._captured:
            return 0.0
        total = sum(len(chunk) for chunk in self._captured)
        return float(total) / float(self.config.sample_rate)
