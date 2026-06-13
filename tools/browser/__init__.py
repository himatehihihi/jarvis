from __future__ import annotations

import webbrowser
from urllib.parse import quote_plus
from typing import Any, Dict

import hands

from ..common import not_implemented, structured_result


def execute(tool: str, params: Dict[str, Any]) -> Dict[str, Any]:
    if tool == "open_website":
        url = str(params.get("url", ""))
        ok = hands.open_website(url)
        return structured_result(ok, tool, f"Opened {url}" if ok else f"Failed to open {url}")
    if tool == "search_google":
        q = str(params.get("query", ""))
        ok = hands.search_google(q)
        return structured_result(ok, tool, f"Searched Google for {q}" if ok else "Google search failed")
    if tool == "search_youtube":
        q = str(params.get("query", ""))
        ok = hands.search_youtube(q)
        return structured_result(ok, tool, f"Searched YouTube for {q}" if ok else "YouTube search failed")
    if tool == "open_tab":
        ok = hands.press_key_command("ctrl+t")
        return structured_result(ok, tool, "Opened new tab" if ok else "Failed to open tab")
    if tool == "close_tab":
        ok = hands.press_key_command("ctrl+w")
        return structured_result(ok, tool, "Closed tab" if ok else "Failed to close tab")
    if tool == "switch_tab":
        direction = str(params.get("direction", "next")).lower()
        key = "ctrl+tab" if direction != "previous" else "ctrl+shift+tab"
        ok = hands.press_key_command(key)
        return structured_result(ok, tool, f"Switched tab {direction}" if ok else "Failed to switch tab")
    if tool == "download_file":
        url = str(params.get("url", "")).strip()
        if not url:
            return structured_result(False, tool, "Missing URL")
        webbrowser.open(url)
        return structured_result(True, tool, f"Opened download URL: {url}")
    return not_implemented(tool)
