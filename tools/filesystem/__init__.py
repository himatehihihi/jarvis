from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict

from ..common import not_implemented, structured_result


def _p(v: str) -> Path:
    return Path(v).expanduser().resolve()


def execute(tool: str, params: Dict[str, Any]) -> Dict[str, Any]:
    if tool == "create_folder":
        p = _p(str(params.get("path", "")))
        p.mkdir(parents=True, exist_ok=True)
        return structured_result(True, tool, f"Created folder: {p}")
    if tool == "rename_file":
        src = _p(str(params.get("source", "")))
        dst = src.with_name(str(params.get("new_name", "")))
        src.rename(dst)
        return structured_result(True, tool, f"Renamed to: {dst.name}")
    if tool == "move_file":
        src = _p(str(params.get("source", "")))
        dst = _p(str(params.get("destination", "")))
        shutil.move(str(src), str(dst))
        return structured_result(True, tool, f"Moved to: {dst}")
    if tool == "copy_file":
        src = _p(str(params.get("source", "")))
        dst = _p(str(params.get("destination", "")))
        shutil.copy2(src, dst)
        return structured_result(True, tool, f"Copied to: {dst}")
    if tool == "delete_file":
        path = _p(str(params.get("path", "")))
        recursive = bool(params.get("recursive", False))
        if path.is_dir() and recursive:
            shutil.rmtree(path)
        elif path.is_dir():
            path.rmdir()
        else:
            path.unlink()
        return structured_result(True, tool, f"Deleted: {path}")
    if tool == "open_folder":
        p = _p(str(params.get("path", "")))
        if not p.exists():
            return structured_result(False, tool, f"Folder not found: {p}")
        subprocess.Popen(["explorer", str(p)])
        return structured_result(True, tool, f"Opened folder: {p}")
    if tool == "search_files":
        root = _p(str(params.get("root", ".")))
        pattern = str(params.get("pattern", "*"))
        matches = [str(x) for x in root.rglob(pattern)][:100]
        return structured_result(True, tool, f"Found {len(matches)} files", matches=matches)
    if tool == "open_downloads":
        p = Path.home() / "Downloads"
        subprocess.Popen(["explorer", str(p)])
        return structured_result(True, tool, "Opened Downloads folder")
    if tool in {"zip_folder", "unzip_file"}:
        return not_implemented(tool, "Use system domain zip/unzip handlers")
    return not_implemented(tool)
