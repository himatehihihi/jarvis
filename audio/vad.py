from __future__ import annotations

import time
from typing import Optional

import numpy as np

from . import AudioConfig


class SileroVADDetector:
    def __init__(self, config: AudioConfig):
        self.config = config
        self.model = None
        self.torch = None
        self.loaded = False
        self.last_probability = 0.0
        self.last_speech_start = 0.0
        self.last_speech_end = 0.0
        self.speech_events = 0
        self._state = "silence"
        self._tail_silence_started: Optional[float] = None
        self._boot_error = ""

    def load(self) -> bool:
        try:
            import torch
            from silero_vad import load_silero_vad

            self.torch = torch
            self.model = load_silero_vad()
            self.loaded = True
            return True
        except Exception as exc:
            self.loaded = False
            self._boot_error = str(exc)
            return False

    def _chunk_prob(self, frame: np.ndarray) -> float:
        if not self.loaded or self.model is None or self.torch is None:
            return 0.0
        frame = np.asarray(frame, dtype=np.float32)
        if frame.size == 0:
            return 0.0
        scores = []
        step = 512
        padded = frame
        rem = len(padded) % step
        if rem:
            padded = np.pad(padded, (0, step - rem), mode="constant")
        for i in range(0, len(padded), step):
            chunk = padded[i : i + step]
            audio = self.torch.from_numpy(chunk)
            score = float(self.model(audio, self.config.sample_rate).item())
            scores.append(score)
        return max(scores) if scores else 0.0

    def update(self, frame: np.ndarray, now: float) -> tuple[bool, bool, float]:
        prob = self._chunk_prob(frame)
        self.last_probability = prob
        threshold = self.config.vad_threshold

        speech_start = False
        speech_end = False

        if prob >= threshold:
            self._tail_silence_started = None
            if self._state != "speech":
                self._state = "speech"
                self.last_speech_start = now
                self.speech_events += 1
                speech_start = True
                print(f"[VAD] speech_start prob={prob:.3f}")
        else:
            if self._state == "speech":
                if self._tail_silence_started is None:
                    self._tail_silence_started = now
                elif (now - self._tail_silence_started) >= self.config.silence_timeout_s:
                    self._state = "silence"
                    self.last_speech_end = now
                    duration = max(0.0, self.last_speech_end - self.last_speech_start)
                    speech_end = True
                    print(f"[VAD] speech_end duration_s={duration:.2f}")
                    self._tail_silence_started = None

        is_speech = self._state == "speech"
        return is_speech, speech_start, speech_end

    def health(self) -> dict:
        return {
            "loaded": self.loaded,
            "threshold": self.config.vad_threshold,
            "silence_timeout_s": self.config.silence_timeout_s,
            "last_probability": round(self.last_probability, 4),
            "speech_events": self.speech_events,
            "boot_error": self._boot_error,
        }

