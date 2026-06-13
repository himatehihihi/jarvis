from __future__ import annotations

from typing import Optional

from .pipeline import AudioPipeline


_PIPELINE: Optional[AudioPipeline] = None


def set_pipeline(pipeline: AudioPipeline) -> None:
    global _PIPELINE
    _PIPELINE = pipeline


def get_pipeline() -> Optional[AudioPipeline]:
    return _PIPELINE

