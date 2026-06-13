from __future__ import annotations

from typing import Any, Dict

from ..common import not_implemented
from ..system import execute as system_execute


def execute(tool: str, params: Dict[str, Any]) -> Dict[str, Any]:
    if tool in {"open_project", "run_python_script", "git_status", "git_commit", "install_package", "run_tests"}:
        return system_execute(tool, params)
    return not_implemented(tool)
