"""Model router for local Ollama usage."""

from __future__ import annotations

from typing import Optional

from .models import OllamaConfig


VISION_KEYWORDS = {
    "image",
    "screenshot",
    "screen shot",
    "photo",
    "picture",
    "camera",
    "webcam",
    "vision",
    "ocr",
}


def needs_vision(prompt: str) -> bool:
    text = (prompt or "").lower()
    return any(keyword in text for keyword in VISION_KEYWORDS)


def choose_model(prompt: str, config: Optional[OllamaConfig] = None) -> str:
    cfg = config or OllamaConfig()
    if needs_vision(prompt):
        return cfg.vision_model
    return cfg.qwen_model
