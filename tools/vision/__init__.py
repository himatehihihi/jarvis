from __future__ import annotations

from typing import Any, Dict

from ..common import not_implemented, structured_result


def execute(tool: str, params: Dict[str, Any]) -> Dict[str, Any]:
    if tool in {"analyze_screen", "read_screen_text", "describe_image"}:
        return structured_result(False, tool, f"{tool} requires configured vision provider", code="not_implemented", provider="none")
    return not_implemented(tool)
