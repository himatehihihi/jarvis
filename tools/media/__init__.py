from __future__ import annotations

from typing import Any, Dict

import hands

from ..common import not_implemented, structured_result


def execute(tool: str, params: Dict[str, Any]) -> Dict[str, Any]:
    if tool == "play_song":
        q = str(params.get("query", "")).strip()
        p = str(params.get("platform", "default")).strip()
        ok = hands.play_song(q, p)
        return structured_result(ok, tool, f"Playing {q}" if ok else "Failed to play media", platform=p)
    if tool == "pause_media":
        ok = hands.press_key_command("playpause")
        return structured_result(ok, tool, "Paused media" if ok else "Failed to pause media")
    if tool == "resume_media":
        ok = hands.press_key_command("playpause")
        return structured_result(ok, tool, "Resumed media" if ok else "Failed to resume media")
    if tool == "next_track":
        ok = hands.press_key_command("nexttrack")
        return structured_result(ok, tool, "Skipped to next track" if ok else "Failed to skip track")
    if tool == "previous_track":
        ok = hands.press_key_command("prevtrack")
        return structured_result(ok, tool, "Moved to previous track" if ok else "Failed previous track")
    if tool == "play_playlist":
        q = str(params.get("query", "")).strip()
        ok = hands.play_song(q, str(params.get("platform", "default")))
        return structured_result(ok, tool, f"Playing playlist {q}" if ok else "Failed to play playlist")
    return not_implemented(tool)
