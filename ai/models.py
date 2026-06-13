"""Model and schema definitions for local Ollama-based AI planning."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional


DomainType = Literal[
    "system",
    "web",
    "files",
    "apps",
    "communication",
    "vision",
    "memory",
    "unknown",
]


@dataclass(frozen=True)
class OllamaConfig:
    """Runtime configuration for local Ollama API usage only."""

    base_url: str = field(default_factory=lambda: os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434"))
    qwen_model: str = field(default_factory=lambda: os.getenv("OLLAMA_QWEN_MODEL", "qwen2.5-coder:7b"))
    vision_model: str = field(default_factory=lambda: os.getenv("OLLAMA_VISION_MODEL", "gemma3:4b"))
    temperature: float = 0.02
    top_p: float = 0.1


@dataclass
class ToolSelection:
    """A single tool recommendation with optional parameter payload."""

    name: str
    confidence: float
    reason: str = ""
    parameters: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AIPlan:
    """Structured output the planner must return."""

    intent: str
    domain: DomainType = "unknown"
    tools: List[ToolSelection] = field(default_factory=list)
    parameters: Dict[str, Any] = field(default_factory=dict)
    response_text: str = ""
    requires_vision: bool = False
    safe_to_execute: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "intent": self.intent,
            "domain": self.domain,
            "tools": [
                {
                    "name": tool.name,
                    "confidence": tool.confidence,
                    "reason": tool.reason,
                    "parameters": tool.parameters,
                }
                for tool in self.tools
            ],
            "parameters": self.parameters,
            "response_text": self.response_text,
            "requires_vision": self.requires_vision,
            "safe_to_execute": self.safe_to_execute,
        }


DEFAULT_OLLAMA_CONFIG = OllamaConfig()
