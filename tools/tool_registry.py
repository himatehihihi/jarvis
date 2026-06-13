"""Centralized tool registry for Jarvis tool metadata and lookup."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Optional

ToolSpec = Dict[str, Any]

SAFE = "SAFE"
CONFIRM_REQUIRED = "CONFIRM_REQUIRED"
BLOCKED_UNLESS_ENABLED = "BLOCKED_UNLESS_ENABLED"


def _spec(tool: str, domain: str, description: str, parameters: Dict[str, Any] | None = None, safety: str = SAFE, aliases: List[str] | None = None) -> ToolSpec:
    return {
        "tool": tool,
        "domain": domain,
        "description": description,
        "parameters": parameters or {},
        "safety_level": safety,
        "dangerous": safety != SAFE,
        "requires_confirmation": safety == CONFIRM_REQUIRED,
        "aliases": aliases or [],
    }


TOOL_REGISTRY: Dict[str, ToolSpec] = {
    "open_app": _spec("open_app", "system", "opens desktop applications", {"app_name": {"type": "string", "required": True}}),
    "close_app": _spec("close_app", "system", "closes current application window"),
    "shutdown_pc": _spec("shutdown_pc", "system", "shutdown computer", safety=CONFIRM_REQUIRED),
    "restart_pc": _spec("restart_pc", "system", "restart computer", safety=CONFIRM_REQUIRED),
    "sleep_pc": _spec("sleep_pc", "system", "sleep computer"),
    "lock_pc": _spec("lock_pc", "system", "lock workstation"),
    "set_volume": _spec("set_volume", "system", "set system volume", {"level": {"type": "integer", "required": True, "min": 0, "max": 100}}),
    "mute_volume": _spec("mute_volume", "system", "toggle mute"),
    "brightness_up": _spec("brightness_up", "system", "increase brightness"),
    "brightness_down": _spec("brightness_down", "system", "decrease brightness"),

    "maximize_window": _spec("maximize_window", "windows", "maximize focused window"),
    "minimize_window": _spec("minimize_window", "windows", "minimize focused window"),
    "switch_window": _spec("switch_window", "windows", "switch active window"),
    "snap_left": _spec("snap_left", "windows", "snap window left"),
    "snap_right": _spec("snap_right", "windows", "snap window right"),
    "focus_window": _spec("focus_window", "windows", "focus window by title", {"title": {"type": "string", "required": False}}),
    "close_window": _spec("close_window", "windows", "close active window"),

    "create_folder": _spec("create_folder", "filesystem", "create folder", {"path": {"type": "string", "required": True}}),
    "rename_file": _spec("rename_file", "filesystem", "rename file", {"source": {"type": "string", "required": True}, "new_name": {"type": "string", "required": True}}),
    "move_file": _spec("move_file", "filesystem", "move file", {"source": {"type": "string", "required": True}, "destination": {"type": "string", "required": True}}),
    "copy_file": _spec("copy_file", "filesystem", "copy file", {"source": {"type": "string", "required": True}, "destination": {"type": "string", "required": True}}),
    "delete_file": _spec("delete_file", "filesystem", "delete file or folder", {"path": {"type": "string", "required": True}, "recursive": {"type": "boolean", "required": False}}, safety=CONFIRM_REQUIRED),
    "open_folder": _spec("open_folder", "filesystem", "open folder in explorer", {"path": {"type": "string", "required": True}}),
    "search_files": _spec("search_files", "filesystem", "search files", {"root": {"type": "string", "required": False}, "pattern": {"type": "string", "required": True}}),
    "open_downloads": _spec("open_downloads", "filesystem", "open downloads folder"),
    "zip_folder": _spec("zip_folder", "system", "zip folder", {"folder_path": {"type": "string", "required": True}, "zip_path": {"type": "string", "required": False}}),
    "unzip_file": _spec("unzip_file", "system", "unzip archive", {"zip_path": {"type": "string", "required": True}, "extract_to": {"type": "string", "required": False}}),

    "open_website": _spec("open_website", "browser", "open website", {"url": {"type": "string", "required": True}}),
    "search_google": _spec("search_google", "browser", "search with Google", {"query": {"type": "string", "required": True}}),
    "search_youtube": _spec("search_youtube", "browser", "search on YouTube", {"query": {"type": "string", "required": True}}),
    "open_tab": _spec("open_tab", "browser", "open browser tab"),
    "close_tab": _spec("close_tab", "browser", "close browser tab"),
    "switch_tab": _spec("switch_tab", "browser", "switch browser tab", {"direction": {"type": "string", "required": False}}),
    "download_file": _spec("download_file", "browser", "download file from URL", {"url": {"type": "string", "required": True}}),

    "create_note": _spec("create_note", "productivity", "create note", {"note": {"type": "string", "required": True}}),
    "append_note": _spec("append_note", "productivity", "append to latest note", {"note": {"type": "string", "required": True}}),
    "read_notes": _spec("read_notes", "productivity", "read notes"),
    "create_reminder": _spec("create_reminder", "productivity", "create reminder", {"task": {"type": "string", "required": True}}),
    "create_timer": _spec("create_timer", "productivity", "create timer", {"duration": {"type": "string", "required": True}}),
    "start_focus_mode": _spec("start_focus_mode", "productivity", "start focus mode"),

    "open_project": _spec("open_project", "developer", "open project folder", {"path": {"type": "string", "required": False}}),
    "run_python_script": _spec("run_python_script", "developer", "run python script", {"script_path": {"type": "string", "required": True}}),
    "git_status": _spec("git_status", "developer", "git status"),
    "git_commit": _spec("git_commit", "developer", "git add and commit", {"message": {"type": "string", "required": True}}, safety=CONFIRM_REQUIRED),
    "install_package": _spec("install_package", "developer", "install python package", {"package": {"type": "string", "required": True}}, safety=BLOCKED_UNLESS_ENABLED),
    "run_tests": _spec("run_tests", "developer", "run test command", {"command": {"type": "string", "required": False}}, safety=BLOCKED_UNLESS_ENABLED),

    "summarize_text": _spec("summarize_text", "ai", "summarize text", {"text": {"type": "string", "required": True}}),
    "rewrite_text": _spec("rewrite_text", "ai", "rewrite text", {"text": {"type": "string", "required": True}}),
    "explain_code": _spec("explain_code", "ai", "explain code", {"text": {"type": "string", "required": True}}),
    "translate_text": _spec("translate_text", "ai", "translate text", {"text": {"type": "string", "required": True}, "target_lang": {"type": "string", "required": False}}),

    "play_song": _spec("play_song", "media", "play song", {"query": {"type": "string", "required": True}, "platform": {"type": "string", "required": False}}),
    "pause_media": _spec("pause_media", "media", "pause media"),
    "resume_media": _spec("resume_media", "media", "resume media"),
    "next_track": _spec("next_track", "media", "next track"),
    "previous_track": _spec("previous_track", "media", "previous track"),
    "play_playlist": _spec("play_playlist", "media", "play playlist", {"query": {"type": "string", "required": True}, "platform": {"type": "string", "required": False}}),

    "analyze_screen": _spec("analyze_screen", "vision", "analyze screen", {"prompt": {"type": "string", "required": False}}),
    "read_screen_text": _spec("read_screen_text", "vision", "read text from screen", {"region": {"type": "string", "required": False}}),
    "describe_image": _spec("describe_image", "vision", "describe image", {"image_path": {"type": "string", "required": False}}),

    "send_whatsapp": _spec("send_whatsapp", "communication", "send WhatsApp message", {"target": {"type": "string", "required": True}, "message": {"type": "string", "required": True}}),
    "whatsapp_call": _spec("whatsapp_call", "communication", "WhatsApp voice call", {"target": {"type": "string", "required": True}}, safety=CONFIRM_REQUIRED),
    "video_call": _spec("video_call", "communication", "WhatsApp video call", {"target": {"type": "string", "required": True}}, safety=CONFIRM_REQUIRED),

    "ai_health_check": _spec("ai_health_check", "diagnostics", "check AI planner and provider health"),
    "ollama_status": _spec("ollama_status", "diagnostics", "check Ollama connectivity and loaded models"),
    "model_status": _spec("model_status", "diagnostics", "check required model availability and load latency"),
    "memory_status": _spec("memory_status", "diagnostics", "check RAM, swap and model memory pressure"),
    "cpu_status": _spec("cpu_status", "diagnostics", "check CPU load"),
    "stt_status": _spec("stt_status", "diagnostics", "check speech-to-text stack status"),
    "wakeword_status": _spec("wakeword_status", "diagnostics", "check wake word configuration status"),
    "vad_status": _spec("vad_status", "diagnostics", "check VAD status"),
    "microphone_status": _spec("microphone_status", "diagnostics", "check microphone status"),
    "executor_status": _spec("executor_status", "diagnostics", "check executor routing status"),
    "validator_status": _spec("validator_status", "diagnostics", "check tool validator behavior"),
    "tool_status": _spec("tool_status", "diagnostics", "check registry tool coverage and domain mapping"),
    "vision_status": _spec("vision_status", "diagnostics", "check vision provider and probe"),
    "ocr_status": _spec("ocr_status", "diagnostics", "check OCR provider and probe"),
    "performance_report": _spec("performance_report", "diagnostics", "build end-to-end performance report"),
    "run_full_diagnostics": _spec("run_full_diagnostics", "diagnostics", "run all diagnostics with recommendations"),
    "recover_ai": _spec("recover_ai", "diagnostics", "recover AI stack by unloading and rewarming models"),
    "unload_models": _spec("unload_models", "diagnostics", "unload inactive/stuck Ollama models"),
    "reload_models": _spec("reload_models", "diagnostics", "reload planner model safely"),
    "emergency_safe_mode": _spec("emergency_safe_mode", "diagnostics", "disable AI planner and force deterministic mode"),
}

ALIASES: Dict[str, str] = {}
for _tool_name, _spec_item in TOOL_REGISTRY.items():
    ALIASES[_tool_name] = _tool_name
    for alias in _spec_item.get("aliases", []):
        ALIASES[alias.strip().lower()] = _tool_name


def get_tool(tool_name: str) -> Optional[ToolSpec]:
    if not tool_name:
        return None
    canonical = ALIASES.get(str(tool_name).strip().lower())
    if not canonical:
        return None
    spec = TOOL_REGISTRY.get(canonical)
    return deepcopy(spec) if spec else None


def list_tools() -> List[ToolSpec]:
    return [deepcopy(spec) for spec in TOOL_REGISTRY.values()]


def list_domains() -> List[str]:
    return sorted({spec["domain"] for spec in TOOL_REGISTRY.values()})


def list_tools_by_domain(domain: str) -> List[ToolSpec]:
    dom = str(domain or "").strip().lower()
    return [deepcopy(spec) for spec in TOOL_REGISTRY.values() if spec.get("domain") == dom]


def canonical_tool_name(tool_name: str) -> Optional[str]:
    if not tool_name:
        return None
    return ALIASES.get(str(tool_name).strip().lower())
