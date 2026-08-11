"""Provider facade for AI planning and connectivity."""

from __future__ import annotations

import os
from typing import Any, Dict

from .gemini_provider import (
    DEFAULT_GEMINI_CONFIG,
    build_live_connect_config,
    check_gemini_connection,
    plan_with_gemini,
    warmup_gemini_model,
)
from .qwen_brain import check_ollama_connection, plan_with_qwen, warmup_qwen_model

_ACTIVE_PROVIDER_OVERRIDE: str | None = None


def get_preferred_ai_provider() -> str:
    raw = str(os.getenv("JARVIS_AI_PROVIDER", "gemini")).strip().lower()
    if raw in {"gemini", "gemini_live", "gemini-live", "google"}:
        return "gemini"
    return "ollama"


def set_active_ai_provider(provider: str | None) -> str:
    global _ACTIVE_PROVIDER_OVERRIDE
    if provider is None:
        _ACTIVE_PROVIDER_OVERRIDE = None
        return get_preferred_ai_provider()
    normalized = str(provider).strip().lower()
    _ACTIVE_PROVIDER_OVERRIDE = "gemini" if normalized == "gemini" else "ollama"
    return _ACTIVE_PROVIDER_OVERRIDE


def get_ai_provider() -> str:
    return _ACTIVE_PROVIDER_OVERRIDE or get_preferred_ai_provider()


def provider_summary() -> Dict[str, Any]:
    provider = get_ai_provider()
    summary: Dict[str, Any] = {
        "provider": provider,
        "preferred_provider": get_preferred_ai_provider(),
        "active_provider": provider,
    }
    if provider == "gemini":
        summary.update(
            {
                "planner_model": DEFAULT_GEMINI_CONFIG.planner_model,
                "live_model": DEFAULT_GEMINI_CONFIG.live_model,
                "uses_single_api_key": True,
                "audio_io_mode": "gemini_live_native_audio",
            }
        )
    return summary


def check_planner_connection(timeout: int = 8) -> Dict[str, Any]:
    provider = get_ai_provider()
    connection = check_ai_connection(timeout=timeout)
    if provider == "gemini":
        connection = dict(connection)
        connection["capability"] = "planner"
    return connection


def warmup_planner_backend(timeout: int = 90) -> Dict[str, Any]:
    provider = get_ai_provider()
    warmup = warmup_ai_backend(timeout=timeout)
    warmup = dict(warmup)
    warmup["capability"] = "planner"
    warmup["provider"] = provider
    return warmup


def plan_command(user_prompt: str, timeout: int = 30, episodic_summary: str = "") -> Dict[str, Any]:
    if get_ai_provider() == "gemini":
        return plan_with_gemini(user_prompt, timeout=timeout, episodic_summary=episodic_summary)
    return plan_with_qwen(user_prompt, timeout=timeout, episodic_summary=episodic_summary)


def check_ai_connection(timeout: int = 8) -> Dict[str, Any]:
    if get_ai_provider() == "gemini":
        return check_gemini_connection()
    return check_ollama_connection(timeout=timeout)


def warmup_ai_backend(timeout: int = 90) -> Dict[str, Any]:
    if get_ai_provider() == "gemini":
        return warmup_gemini_model(timeout=timeout)
    return warmup_qwen_model(timeout=timeout)


__all__ = [
    "build_live_connect_config",
    "check_ai_connection",
    "check_planner_connection",
    "get_ai_provider",
    "get_preferred_ai_provider",
    "plan_command",
    "provider_summary",
    "set_active_ai_provider",
    "warmup_ai_backend",
    "warmup_planner_backend",
]
