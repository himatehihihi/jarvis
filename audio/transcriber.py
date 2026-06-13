from __future__ import annotations

import time
from typing import Tuple

import numpy as np
from faster_whisper import WhisperModel

from . import AudioConfig


class FasterWhisperTranscriber:
    def __init__(self, config: AudioConfig):
        self.config = config
        self.model = WhisperModel(config.whisper_model, compute_type="int8")
        self.transcriptions = 0
        self.failures = 0
        self.last_latency_s = 0.0
        self.last_transcript = ""

    def transcribe(self, audio: np.ndarray) -> Tuple[str, float]:
        if audio.size == 0:
            return "", 0.0
        print("[STT] transcription_started")
        start = time.perf_counter()
        try:
            segments, _ = self.model.transcribe(
                audio.astype(np.float32),
                beam_size=self.config.beam_size,
                temperature=self.config.temperature,
                vad_filter=False,
                language="en",
            )
            text = " ".join(seg.text for seg in segments).strip().lower()
            latency = time.perf_counter() - start
            self.last_latency_s = latency
            self.last_transcript = text
            self.transcriptions += 1
            print(f"[STT] transcription_finished latency_s={latency:.3f}")
            print(f"[STT] transcript={text}")
            return text, latency
        except Exception:
            self.failures += 1
            latency = time.perf_counter() - start
            self.last_latency_s = latency
            raise

    def health(self) -> dict:
        return {
            "loaded": True,
            "model": self.config.whisper_model,
            "compute_type": "int8",
            "beam_size": self.config.beam_size,
            "temperature": self.config.temperature,
            "transcriptions": self.transcriptions,
            "failures": self.failures,
            "last_latency_s": round(self.last_latency_s, 3),
            "last_transcript": self.last_transcript,
        }
