from __future__ import annotations

import time
from typing import Any, Dict


NOT_IMPLEMENTED_CODE = "not_implemented"


def structured_result(success: bool, tool: str, message: str = "", duration: float = 0.0, **kwargs: Any) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "success": bool(success),
        "tool": tool,
        "duration": round(float(duration), 3),
    }
    if success:
        out["message"] = message
    else:
        out["error"] = message
    out.update(kwargs)
    return out


def not_implemented(tool: str, message: str = "Tool is not implemented yet") -> Dict[str, Any]:
    return structured_result(False, tool, message, code=NOT_IMPLEMENTED_CODE)


def run_logged(tool: str, fn):
    start = time.perf_counter()
    print(f"[EXECUTOR] tool={tool}")
    try:
        result = fn()
        duration = time.perf_counter() - start
        if isinstance(result, dict):
            result.setdefault("tool", tool)
            result.setdefault("duration", round(duration, 3))
            print(f"[EXECUTOR] status={'success' if result.get('success') else 'failure'}")
            print(f"[EXECUTOR] duration={duration:.2f}s")
            return result
        if isinstance(result, bool):
            msg = "Command executed" if result else "Command failed"
            out = structured_result(result, tool, msg, duration)
            print(f"[EXECUTOR] status={'success' if result else 'failure'}")
            print(f"[EXECUTOR] duration={duration:.2f}s")
            return out
        out = structured_result(True, tool, str(result), duration)
        print("[EXECUTOR] status=success")
        print(f"[EXECUTOR] duration={duration:.2f}s")
        return out
    except Exception as exc:
        duration = time.perf_counter() - start
        print("[EXECUTOR] status=failure")
        print(f"[EXECUTOR] duration={duration:.2f}s")
        return structured_result(False, tool, str(exc), duration)
