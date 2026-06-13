from __future__ import annotations

from typing import Any, Dict

import hands

from ..common import not_implemented, structured_result


def execute(tool: str, params: Dict[str, Any]) -> Dict[str, Any]:
    if tool == "maximize_window":
        ok = hands.press_key_command("win+up")
        return structured_result(ok, tool, "Window maximized" if ok else "Failed to maximize window")
    if tool == "minimize_window":
        ok = hands.press_key_command("win+down")
        return structured_result(ok, tool, "Window minimized" if ok else "Failed to minimize window")
    if tool == "switch_window":
        ok = hands.switch_window()
        return structured_result(ok, tool, "Switched window" if ok else "Failed to switch window")
    if tool == "snap_left":
        ok = hands.press_key_command("win+left")
        return structured_result(ok, tool, "Snapped left" if ok else "Failed to snap left")
    if tool == "snap_right":
        ok = hands.press_key_command("win+right")
        return structured_result(ok, tool, "Snapped right" if ok else "Failed to snap right")
    if tool == "focus_window":
        return not_implemented(tool, "Focus by title provider not implemented yet")
    if tool == "close_window":
        ok = hands.close_active_window()
        return structured_result(ok, tool, "Closed window" if ok else "Failed to close window")
    return not_implemented(tool)
