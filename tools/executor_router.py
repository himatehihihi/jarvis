from __future__ import annotations

from typing import Any, Dict

from .tool_registry import get_tool
from .common import not_implemented, run_logged
from . import system, windows, filesystem, browser, productivity, developer, ai, media, vision, communication, diagnostics

_DOMAIN_EXECUTORS = {
    "system": system.execute,
    "windows": windows.execute,
    "filesystem": filesystem.execute,
    "browser": browser.execute,
    "productivity": productivity.execute,
    "developer": developer.execute,
    "ai": ai.execute,
    "media": media.execute,
    "vision": vision.execute,
    "communication": communication.execute,
    "diagnostics": diagnostics.execute,
}


def execute_tool(tool: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
    spec = get_tool(tool)
    if not spec:
        return not_implemented(tool, "Tool not registered")
    domain = spec.get("domain")
    handler = _DOMAIN_EXECUTORS.get(domain)
    if not handler:
        return not_implemented(tool, f"No domain executor for '{domain}'")
    return run_logged(tool, lambda: handler(tool, parameters or {}))
