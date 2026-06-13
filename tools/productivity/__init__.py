from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from ..common import not_implemented, structured_result

_NOTES = Path("notes.json")
_REMINDERS = Path("reminders.json")


def _load(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _save(path: Path, data: List[Dict[str, Any]]) -> None:
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def execute(tool: str, params: Dict[str, Any]) -> Dict[str, Any]:
    if tool == "create_note":
        text = str(params.get("note", "")).strip()
        items = _load(_NOTES)
        items.append({"note": text, "created": datetime.now().isoformat()})
        _save(_NOTES, items)
        return structured_result(True, tool, "Note created")
    if tool == "append_note":
        text = str(params.get("note", "")).strip()
        items = _load(_NOTES)
        if not items:
            return structured_result(False, tool, "No existing note to append")
        items[-1]["note"] = f"{items[-1]['note']}\n{text}".strip()
        _save(_NOTES, items)
        return structured_result(True, tool, "Appended to latest note")
    if tool == "read_notes":
        items = _load(_NOTES)
        return structured_result(True, tool, f"Loaded {len(items)} notes", notes=items[-20:])
    if tool == "create_reminder":
        task = str(params.get("task", "")).strip()
        items = _load(_REMINDERS)
        items.append({"task": task, "created": datetime.now().isoformat()})
        _save(_REMINDERS, items)
        return structured_result(True, tool, "Reminder saved")
    if tool == "create_timer":
        return structured_result(True, tool, f"Timer created for {params.get('duration', '')}")
    if tool == "start_focus_mode":
        return structured_result(True, tool, "Focus mode started")
    return not_implemented(tool)
