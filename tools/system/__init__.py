from __future__ import annotations

import os
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Any, Dict

import hands

from ..common import not_implemented, structured_result


_ROOT = Path.cwd().resolve()
_LAST_MUTED_STATE: bool | None = None


def _safe_resolve(path: str) -> Path:
    return Path(path).expanduser().resolve()


def _set_mute(muted: bool) -> bool:
    global _LAST_MUTED_STATE
    if _LAST_MUTED_STATE is muted:
        return True
    ok = hands.press_key_command("volumemute")
    if ok:
        _LAST_MUTED_STATE = muted
    return ok


def execute(tool: str, params: Dict[str, Any]) -> Dict[str, Any]:
    if tool == "open_app":
        app = str(params.get("app_name", "")).strip()
        ok = hands.open_app(app)
        return structured_result(ok, tool, f"Opened {app}" if ok else f"Could not open {app}")
    if tool == "close_app":
        ok = hands.close_active_window()
        return structured_result(ok, tool, "Closed active app" if ok else "Failed to close active app")
    if tool == "shutdown_pc":
        rc = os.system("shutdown /s /t 0")
        return structured_result(rc == 0, tool, "Shutting down PC")
    if tool == "restart_pc":
        rc = os.system("shutdown /r /t 0")
        return structured_result(rc == 0, tool, "Restarting PC")
    if tool == "sleep_pc":
        rc = os.system("rundll32.exe powrprof.dll,SetSuspendState 0,1,0")
        return structured_result(rc == 0, tool, "Putting PC to sleep")
    if tool == "lock_pc":
        rc = os.system("rundll32.exe user32.dll,LockWorkStation")
        return structured_result(rc == 0, tool, "Locked PC")
    if tool == "set_volume":
        level = int(params.get("level", 0))
        if not 0 <= level <= 100:
            return structured_result(False, tool, "Volume must be between 0 and 100")
        script = f"(New-Object -ComObject WScript.Shell).SendKeys([char]174*50); (New-Object -ComObject WScript.Shell).SendKeys([char]175*{max(0, min(50, level//2))})"
        rc = subprocess.call(["powershell", "-NoProfile", "-Command", script])
        return structured_result(rc == 0, tool, f"Set volume to {level}")
    if tool == "mute_volume":
        ok = hands.press_key_command("volumemute")
        return structured_result(ok, tool, "Toggled mute" if ok else "Failed to toggle mute")
    if tool == "set_mute":
        muted = bool(params.get("muted", False))
        ok = _set_mute(muted)
        return structured_result(ok, tool, "Muted volume" if muted and ok else "Unmuted volume" if ok else "Failed to change mute state", muted=muted)
    if tool == "volume_up":
        steps = int(params.get("steps", 5))
        ok = all(hands.press_key_command("volumeup") for _ in range(max(1, min(50, steps))))
        return structured_result(ok, tool, "Increased volume" if ok else "Failed to increase volume", steps=steps)
    if tool == "volume_down":
        steps = int(params.get("steps", 5))
        ok = all(hands.press_key_command("volumedown") for _ in range(max(1, min(50, steps))))
        return structured_result(ok, tool, "Decreased volume" if ok else "Failed to decrease volume", steps=steps)
    if tool in {"brightness_up", "brightness_down"}:
        return not_implemented(tool, "Brightness control provider not configured yet")
    if tool == "open_project":
        path = str(params.get("path", str(_ROOT)))
        p = _safe_resolve(path)
        if not p.exists():
            return structured_result(False, tool, f"Path not found: {p}")
        os.startfile(str(p))
        return structured_result(True, tool, f"Opened project at {p}")
    if tool == "run_python_script":
        script = _safe_resolve(str(params.get("script_path", "")))
        if not script.exists():
            return structured_result(False, tool, f"Script not found: {script}")
        completed = subprocess.run(["python", str(script)], capture_output=True, text=True)
        return structured_result(completed.returncode == 0, tool, "Script executed", stdout=completed.stdout[-1000:], stderr=completed.stderr[-1000:], returncode=completed.returncode)
    if tool == "install_package":
        package = str(params.get("package", "")).strip()
        completed = subprocess.run(["python", "-m", "pip", "install", package], capture_output=True, text=True)
        return structured_result(completed.returncode == 0, tool, f"Installed {package}", stdout=completed.stdout[-1000:], stderr=completed.stderr[-1000:], returncode=completed.returncode)
    if tool == "run_tests":
        cmd = str(params.get("command", "pytest")).strip().split()
        completed = subprocess.run(cmd, capture_output=True, text=True)
        return structured_result(completed.returncode == 0, tool, "Tests executed", stdout=completed.stdout[-1500:], stderr=completed.stderr[-1500:], returncode=completed.returncode)
    if tool == "git_status":
        completed = subprocess.run(["git", "status", "--short"], capture_output=True, text=True)
        return structured_result(completed.returncode == 0, tool, "Git status collected", stdout=completed.stdout[-2000:], stderr=completed.stderr[-500:])
    if tool == "git_commit":
        msg = str(params.get("message", "update"))
        add = subprocess.run(["git", "add", "-A"], capture_output=True, text=True)
        if add.returncode != 0:
            return structured_result(False, tool, "git add failed", stderr=add.stderr[-500:])
        commit = subprocess.run(["git", "commit", "-m", msg], capture_output=True, text=True)
        return structured_result(commit.returncode == 0, tool, "Commit attempted", stdout=commit.stdout[-1000:], stderr=commit.stderr[-1000:], returncode=commit.returncode)
    if tool == "zip_folder":
        source = _safe_resolve(str(params.get("folder_path", "")))
        out = _safe_resolve(str(params.get("zip_path", f"{source}.zip")))
        if not source.exists() or not source.is_dir():
            return structured_result(False, tool, f"Folder not found: {source}")
        shutil.make_archive(str(out.with_suffix("")), "zip", str(source))
        return structured_result(True, tool, f"Created zip: {out}")
    if tool == "unzip_file":
        zip_path = _safe_resolve(str(params.get("zip_path", "")))
        dest = _safe_resolve(str(params.get("extract_to", zip_path.parent)))
        if not zip_path.exists():
            return structured_result(False, tool, f"Zip not found: {zip_path}")
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(dest)
        return structured_result(True, tool, f"Extracted to: {dest}")
    return not_implemented(tool)
