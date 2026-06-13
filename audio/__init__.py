from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class AudioConfig:
    sample_rate: int = int(os.getenv("JARVIS_AUDIO_SAMPLE_RATE", "16000"))
    channels: int = 1
    block_duration_ms: int = int(os.getenv("JARVIS_AUDIO_BLOCK_MS", "80"))
    wake_threshold: float = float(os.getenv("JARVIS_WAKE_THRESHOLD", "0.45"))
    wake_cooldown_s: float = float(os.getenv("JARVIS_WAKE_COOLDOWN_S", "1.0"))
    vad_threshold: float = float(os.getenv("JARVIS_VAD_THRESHOLD", "0.45"))
    silence_timeout_s: float = float(os.getenv("JARVIS_SILENCE_TIMEOUT_S", "0.9"))
    pre_roll_s: float = float(os.getenv("JARVIS_PRE_ROLL_S", "0.9"))
    post_roll_s: float = float(os.getenv("JARVIS_POST_ROLL_S", "0.25"))
    command_timeout_s: float = float(os.getenv("JARVIS_COMMAND_TIMEOUT_S", "6.0"))
    beam_size: int = int(os.getenv("JARVIS_STT_BEAM_SIZE", "2"))
    temperature: float = float(os.getenv("JARVIS_STT_TEMPERATURE", "0.0"))
    transcription_timeout_s: float = float(os.getenv("JARVIS_STT_TIMEOUT_S", "20"))
    wakeword_model_hint: str = os.getenv("JARVIS_WAKEWORD_HINT", "jarvis")
    whisper_model: str = os.getenv("JARVIS_WHISPER_MODEL", "small.en")


DEFAULT_AUDIO_CONFIG = AudioConfig()
