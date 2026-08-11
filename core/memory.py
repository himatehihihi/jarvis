"""Persistent task and alarm storage."""

import json
import msvcrt
import os
import threading
import time
from datetime import datetime, timedelta

import hands

from core.runtime import speak

MEMORY_FILE = "memory.json"
MEMORY_LOCK_FILE = f"{MEMORY_FILE}.lock"
EPISODIC_MEMORY_FILE = "episodic_memory.json"
EPISODIC_MEMORY_LOCK_FILE = f"{EPISODIC_MEMORY_FILE}.lock"
ARCHIVED_TASK_RETENTION_DAYS = 30
ARCHIVED_ALARM_RETENTION_DAYS = 14
MAX_EPISODES = 50
EPISODIC_SUMMARY_MAX_CHARS = 700
LOCK_RETRY_DELAY_SECONDS = 0.05
LOCK_TIMEOUT_SECONDS = 5.0
_MEMORY_MUTEX = threading.RLock()
_EPISODIC_MUTEX = threading.RLock()


def _log_memory(event, **fields):
    details = " ".join(f"{key}={value}" for key, value in sorted(fields.items()))
    if details:
        print(f"[MEMORY] {event} {details}")
    else:
        print(f"[MEMORY] {event}")


def _log_episodic(event, **fields):
    details = " ".join(f"{key}={value}" for key, value in sorted(fields.items()))
    if details:
        print(f"[EPISODIC] {event} {details}")
    else:
        print(f"[EPISODIC] {event}")


def _default_memory():
    return {
        "tasks": [],
        "alarms": [],
        "archived_tasks": [],
        "archived_alarms": [],
    }


def _default_episodic_memory():
    return {"episodes": []}


class _MemoryFileLock:
    def __init__(self, lock_path):
        self.lock_path = lock_path

    def __enter__(self):
        start = time.time()
        self._file = open(self.lock_path, "a+b")
        while True:
            try:
                self._file.seek(0)
                msvcrt.locking(self._file.fileno(), msvcrt.LK_NBLCK, 1)
                return self
            except OSError:
                if time.time() - start >= LOCK_TIMEOUT_SECONDS:
                    self._file.close()
                    raise TimeoutError(f"Timed out acquiring file lock for {self.lock_path}")
                time.sleep(LOCK_RETRY_DELAY_SECONDS)

    def __exit__(self, exc_type, exc, tb):
        try:
            self._file.seek(0)
            msvcrt.locking(self._file.fileno(), msvcrt.LK_UNLCK, 1)
        finally:
            self._file.close()


def _parse_iso(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except Exception:
        return None


def _safe_string(value, limit=160):
    text = str(value or "").replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _format_execution_result(result):
    if isinstance(result, dict):
        if result.get("message"):
            return _safe_string(result.get("message"), limit=160)
        if result.get("error"):
            return "error: " + _safe_string(result.get("error"), limit=150)
        if "success" in result:
            return f"success={bool(result.get('success'))}"
    if isinstance(result, bool):
        return f"success={result}"
    if result is None:
        return "result=None"
    return _safe_string(result, limit=160)


def _normalize_episode(episode):
    if not isinstance(episode, dict):
        return None
    command = _safe_string(episode.get("user_command"), limit=200)
    if not command:
        return None
    planner_output = episode.get("planner_output") if isinstance(episode.get("planner_output"), dict) else {}
    execution_result = episode.get("execution_result")
    timestamp = episode.get("timestamp")
    if _parse_iso(timestamp) is None:
        timestamp = datetime.now().isoformat()
    return {
        "user_command": command,
        "planner_output": planner_output,
        "execution_result": execution_result,
        "timestamp": timestamp,
    }


def _archive_task(memory, task, reason, now=None):
    now = now or datetime.now()
    archived = dict(task)
    archived["done"] = True
    archived["completion_reason"] = reason
    archived["archived_at"] = now.isoformat()
    memory["archived_tasks"].append(archived)
    _log_memory("task_archived", task=archived.get("task", ""), reason=reason)


def _archive_alarm(memory, alarm, reason, now=None):
    now = now or datetime.now()
    archived = dict(alarm)
    archived["status"] = reason
    archived["archived_at"] = now.isoformat()
    memory["archived_alarms"].append(archived)
    _log_memory(
        "alarm_archived",
        label=archived.get("label", ""),
        due=archived.get("due", ""),
        reason=reason,
    )


def _cleanup_memory(memory, archive_due_alarms=True):
    now = datetime.now()
    changed = False
    cleanup = {
        "archived_completed_tasks": 0,
        "archived_due_alarms": 0,
        "pruned_archived_tasks": 0,
        "pruned_archived_alarms": 0,
        "dropped_invalid_tasks": 0,
        "dropped_invalid_alarms": 0,
    }

    active_tasks = []
    for task in memory["tasks"]:
        if not isinstance(task, dict):
            cleanup["dropped_invalid_tasks"] += 1
            changed = True
            continue
        if task.get("done", False):
            _archive_task(memory, task, reason="completed", now=now)
            cleanup["archived_completed_tasks"] += 1
            changed = True
            continue
        active_tasks.append(task)
    memory["tasks"] = active_tasks

    active_alarms = []
    for alarm in memory["alarms"]:
        if not isinstance(alarm, dict):
            cleanup["dropped_invalid_alarms"] += 1
            changed = True
            continue
        due_at = _parse_iso(alarm.get("due"))
        if due_at is None:
            _archive_alarm(memory, alarm, reason="invalid_due", now=now)
            cleanup["archived_due_alarms"] += 1
            changed = True
            continue
        if archive_due_alarms and due_at <= now:
            _archive_alarm(memory, alarm, reason="expired", now=now)
            cleanup["archived_due_alarms"] += 1
            changed = True
            continue
        active_alarms.append(alarm)
    memory["alarms"] = active_alarms

    task_cutoff = now - timedelta(days=ARCHIVED_TASK_RETENTION_DAYS)
    kept_archived_tasks = []
    for task in memory["archived_tasks"]:
        archived_at = _parse_iso(task.get("archived_at")) or _parse_iso(task.get("created"))
        if archived_at is not None and archived_at < task_cutoff:
            cleanup["pruned_archived_tasks"] += 1
            changed = True
            continue
        kept_archived_tasks.append(task)
    memory["archived_tasks"] = kept_archived_tasks

    alarm_cutoff = now - timedelta(days=ARCHIVED_ALARM_RETENTION_DAYS)
    kept_archived_alarms = []
    for alarm in memory["archived_alarms"]:
        archived_at = _parse_iso(alarm.get("archived_at")) or _parse_iso(alarm.get("due"))
        if archived_at is not None and archived_at < alarm_cutoff:
            cleanup["pruned_archived_alarms"] += 1
            changed = True
            continue
        kept_archived_alarms.append(alarm)
    memory["archived_alarms"] = kept_archived_alarms

    if any(cleanup.values()):
        _log_memory("cleanup", **cleanup)
    return changed


def _normalize_memory(data, archive_due_alarms=True):
    memory = dict(data) if isinstance(data, dict) else {}
    changed = False
    defaults = _default_memory()
    for key, default_value in defaults.items():
        if not isinstance(memory.get(key), list):
            memory[key] = list(default_value)
            changed = True
    changed = _cleanup_memory(memory, archive_due_alarms=archive_due_alarms) or changed
    return memory, changed


def _normalize_episodic_memory(data):
    memory = dict(data) if isinstance(data, dict) else {}
    changed = False
    episodes = memory.get("episodes")
    if not isinstance(episodes, list):
        episodes = []
        changed = True
    normalized = []
    for episode in episodes:
        item = _normalize_episode(episode)
        if item is None:
            changed = True
            continue
        normalized.append(item)
    normalized.sort(key=lambda item: item.get("timestamp", ""))
    trimmed = max(0, len(normalized) - MAX_EPISODES)
    if trimmed:
        normalized = normalized[-MAX_EPISODES:]
        changed = True
        _log_episodic("episode_trim", kept=len(normalized), removed=trimmed)
    memory["episodes"] = normalized
    return memory, changed


def prune_expired_alarms():
    with _MEMORY_MUTEX:
        with _MemoryFileLock(MEMORY_LOCK_FILE):
            memory = _load_memory_unlocked(archive_due_alarms=True)
            return memory.get("archived_alarms", [])


def load_memory():
    with _MEMORY_MUTEX:
        with _MemoryFileLock(MEMORY_LOCK_FILE):
            return _load_memory_unlocked(archive_due_alarms=True)


def _load_memory_unlocked(archive_due_alarms=True):
    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as file:
            raw = json.load(file)
        memory, changed = _normalize_memory(raw, archive_due_alarms=archive_due_alarms)
        _log_memory(
            "load",
            path=MEMORY_FILE,
            tasks=len(memory["tasks"]),
            alarms=len(memory["alarms"]),
            archived_tasks=len(memory["archived_tasks"]),
            archived_alarms=len(memory["archived_alarms"]),
            repaired=changed,
        )
        if changed:
            _save_memory_unlocked(memory)
        return memory
    except FileNotFoundError:
        memory = _default_memory()
        _log_memory("load_missing_file", path=MEMORY_FILE)
        return memory
    except json.JSONDecodeError as exc:
        backup_name = f"{MEMORY_FILE}.corrupt.{datetime.now().strftime('%Y%m%d%H%M%S')}"
        backup_ok = False
        try:
            if os.path.exists(MEMORY_FILE):
                os.replace(MEMORY_FILE, backup_name)
                backup_ok = True
        except Exception as backup_exc:
            _log_memory("corrupt_backup_failed", path=MEMORY_FILE, error=repr(backup_exc))
        _log_memory("load_corrupt_file", path=MEMORY_FILE, backup=backup_name if backup_ok else "unavailable", error=repr(exc))
        if not backup_ok:
            return _default_memory()
        memory = _default_memory()
        _save_memory_unlocked(memory)
        return memory
    except Exception as exc:
        _log_memory("load_failed", path=MEMORY_FILE, error=repr(exc))
        return _default_memory()


def save_memory(data):
    with _MEMORY_MUTEX:
        with _MemoryFileLock(MEMORY_LOCK_FILE):
            _save_memory_unlocked(data)


def _save_memory_unlocked(data):
    memory, _ = _normalize_memory(data, archive_due_alarms=True)
    temp_path = f"{MEMORY_FILE}.{os.getpid()}.{threading.get_ident()}.tmp"
    with open(temp_path, "w", encoding="utf-8") as file:
        json.dump(memory, file, indent=2)
    os.replace(temp_path, MEMORY_FILE)
    _log_memory(
        "save",
        path=MEMORY_FILE,
        tasks=len(memory["tasks"]),
        alarms=len(memory["alarms"]),
        archived_tasks=len(memory["archived_tasks"]),
        archived_alarms=len(memory["archived_alarms"]),
    )


def _load_episodic_memory_unlocked():
    try:
        with open(EPISODIC_MEMORY_FILE, "r", encoding="utf-8") as file:
            raw = json.load(file)
        memory, changed = _normalize_episodic_memory(raw)
        _log_episodic(
            "retrieve",
            episodes=len(memory["episodes"]),
            path=EPISODIC_MEMORY_FILE,
            repaired=changed,
        )
        if changed:
            _save_episodic_memory_unlocked(memory)
        return memory
    except FileNotFoundError:
        _log_episodic("retrieve_missing_file", path=EPISODIC_MEMORY_FILE)
        return _default_episodic_memory()
    except json.JSONDecodeError as exc:
        backup_name = f"{EPISODIC_MEMORY_FILE}.corrupt.{datetime.now().strftime('%Y%m%d%H%M%S')}"
        backup_ok = False
        try:
            if os.path.exists(EPISODIC_MEMORY_FILE):
                os.replace(EPISODIC_MEMORY_FILE, backup_name)
                backup_ok = True
        except Exception as backup_exc:
            _log_episodic("memory_failure", action="backup_corrupt", error=repr(backup_exc), path=EPISODIC_MEMORY_FILE)
        _log_episodic(
            "memory_failure",
            action="load_corrupt",
            backup=backup_name if backup_ok else "unavailable",
            error=repr(exc),
            path=EPISODIC_MEMORY_FILE,
        )
        if not backup_ok:
            return _default_episodic_memory()
        memory = _default_episodic_memory()
        _save_episodic_memory_unlocked(memory)
        return memory
    except Exception as exc:
        _log_episodic("memory_failure", action="load", error=repr(exc), path=EPISODIC_MEMORY_FILE)
        return _default_episodic_memory()


def _save_episodic_memory_unlocked(data):
    memory, _ = _normalize_episodic_memory(data)
    temp_path = f"{EPISODIC_MEMORY_FILE}.{os.getpid()}.{threading.get_ident()}.tmp"
    with open(temp_path, "w", encoding="utf-8") as file:
        json.dump(memory, file, indent=2)
    os.replace(temp_path, EPISODIC_MEMORY_FILE)
    _log_episodic("save", episodes=len(memory["episodes"]), path=EPISODIC_MEMORY_FILE)


def store_task(task):
    with _MEMORY_MUTEX:
        with _MemoryFileLock(MEMORY_LOCK_FILE):
            memory = _load_memory_unlocked(archive_due_alarms=True)

            for item in memory["tasks"]:
                if item.get("task") == task and not item.get("done", False):
                    _log_memory("task_duplicate_ignored", task=task)
                    return

            memory["tasks"].append({
                "task": task,
                "created": datetime.now().isoformat(),
                "done": False,
            })

            _save_memory_unlocked(memory)
    speak(f"Noted - {task}")


def get_pending():
    with _MEMORY_MUTEX:
        with _MemoryFileLock(MEMORY_LOCK_FILE):
            memory = _load_memory_unlocked(archive_due_alarms=True)
            return [
                item
                for item in memory["tasks"]
                if not item.get("done", False) and hands.can_handle(item.get("task", ""))
            ]


def mark_done(task):
    with _MEMORY_MUTEX:
        with _MemoryFileLock(MEMORY_LOCK_FILE):
            memory = _load_memory_unlocked(archive_due_alarms=True)
            updated = False
            now = datetime.now()
            remaining = []
            for item in memory["tasks"]:
                if item.get("task") == task and not item.get("done", False):
                    item["done"] = True
                    item["completed_at"] = now.isoformat()
                    _archive_task(memory, item, reason="completed", now=now)
                    _log_memory("task_completed", task=task)
                    updated = True
                    continue
                remaining.append(item)
            memory["tasks"] = remaining
            if updated:
                _save_memory_unlocked(memory)


def clear_tasks():
    with _MEMORY_MUTEX:
        with _MemoryFileLock(MEMORY_LOCK_FILE):
            memory = _load_memory_unlocked(archive_due_alarms=True)
            now = datetime.now()
            cleared = 0
            for task in list(memory["tasks"]):
                task["done"] = True
                task["completed_at"] = now.isoformat()
                _archive_task(memory, task, reason="cleared", now=now)
                cleared += 1
            memory["tasks"] = []
            _log_memory("task_clear", count=cleared)
            _save_memory_unlocked(memory)


def forget_task(task_text):
    with _MEMORY_MUTEX:
        with _MemoryFileLock(MEMORY_LOCK_FILE):
            memory = _load_memory_unlocked(archive_due_alarms=True)
            changed = False
            now = datetime.now()
            remaining = []
            for task in memory["tasks"]:
                if not task.get("done", False) and task_text in task.get("task", ""):
                    task["done"] = True
                    task["completed_at"] = now.isoformat()
                    _archive_task(memory, task, reason="forgotten", now=now)
                    _log_memory("task_completed", task=task.get("task", ""), reason="forgotten")
                    changed = True
                    continue
                remaining.append(task)
            memory["tasks"] = remaining
            if changed:
                _save_memory_unlocked(memory)
            return changed


def store_alarm(label, due_time, kind="alarm"):
    with _MEMORY_MUTEX:
        with _MemoryFileLock(MEMORY_LOCK_FILE):
            memory = _load_memory_unlocked(archive_due_alarms=True)
            memory["alarms"].append({
                "label": label,
                "due": due_time.isoformat(),
                "kind": kind,
                "created": datetime.now().isoformat(),
            })
            _save_memory_unlocked(memory)


def get_alarms():
    with _MEMORY_MUTEX:
        with _MemoryFileLock(MEMORY_LOCK_FILE):
            memory = _load_memory_unlocked(archive_due_alarms=True)
            return memory.get("alarms", [])


def remove_alarm(alarm):
    with _MEMORY_MUTEX:
        with _MemoryFileLock(MEMORY_LOCK_FILE):
            memory = _load_memory_unlocked(archive_due_alarms=True)
            removed = False
            remaining = []
            now = datetime.now()
            for item in memory.get("alarms", []):
                if item.get("due") == alarm.get("due") and item.get("label") == alarm.get("label"):
                    _archive_alarm(memory, item, reason="removed", now=now)
                    removed = True
                    continue
                remaining.append(item)
            memory["alarms"] = remaining
            if removed:
                _save_memory_unlocked(memory)


def check_due_alarms():
    with _MEMORY_MUTEX:
        with _MemoryFileLock(MEMORY_LOCK_FILE):
            memory = _load_memory_unlocked(archive_due_alarms=False)
            now = datetime.now()
            triggered = []
            remaining = []
            for alarm in memory.get("alarms", []):
                due_at = _parse_iso(alarm.get("due"))
                if due_at is None:
                    _archive_alarm(memory, alarm, reason="invalid_due", now=now)
                    continue
                if due_at <= now:
                    triggered.append(alarm)
                    _archive_alarm(memory, alarm, reason="triggered", now=now)
                    _log_memory("alarm_trigger", label=alarm.get("label", ""), due=alarm.get("due", ""))
                    continue
                remaining.append(alarm)
            if triggered or len(remaining) != len(memory.get("alarms", [])):
                memory["alarms"] = remaining
                _save_memory_unlocked(memory)
            return triggered


def add_episode(user_command, planner_output, execution_result):
    try:
        command = _safe_string(user_command, limit=200)
        if not command:
            return
        if not isinstance(execution_result, dict) or not execution_result.get("success"):
            return
        episode = _normalize_episode({
            "user_command": command,
            "planner_output": planner_output if isinstance(planner_output, dict) else {},
            "execution_result": execution_result,
            "timestamp": datetime.now().isoformat(),
        })
        if episode is None:
            return
        with _EPISODIC_MUTEX:
            with _MemoryFileLock(EPISODIC_MEMORY_LOCK_FILE):
                memory = _load_episodic_memory_unlocked()
                before = len(memory["episodes"])
                memory["episodes"].append(episode)
                memory, _ = _normalize_episodic_memory(memory)
                after = len(memory["episodes"])
                _save_episodic_memory_unlocked(memory)
                _log_episodic("episode_created", command=command, episodes=after)
                if after < before + 1:
                    _log_episodic("episode_trim", kept=after, removed=(before + 1) - after)
    except Exception as exc:
        _log_episodic("memory_failure", action="add_episode", error=repr(exc))


def get_recent_episodes(limit=5):
    try:
        safe_limit = max(0, int(limit))
        with _EPISODIC_MUTEX:
            with _MemoryFileLock(EPISODIC_MEMORY_LOCK_FILE):
                memory = _load_episodic_memory_unlocked()
                episodes = memory.get("episodes", [])
                recent = list(episodes[-safe_limit:] if safe_limit else [])
                _log_episodic("episode_retrieval", count=len(recent), requested=safe_limit)
                return recent
    except Exception as exc:
        _log_episodic("memory_failure", action="get_recent_episodes", error=repr(exc))
        return []


def summarize_recent_episodes(limit=5, max_chars=EPISODIC_SUMMARY_MAX_CHARS):
    try:
        hard_limit = max(1, min(int(max_chars), EPISODIC_SUMMARY_MAX_CHARS))
        episodes = get_recent_episodes(limit=limit)
        if not episodes:
            _log_episodic("summary_generated", characters=0, episodes=0)
            return ""

        lines = []
        for episode in episodes:
            planner_output = episode.get("planner_output") or {}
            tool_name = planner_output.get("tool") or "unknown"
            domain = planner_output.get("domain") or "unknown"
            result_text = _format_execution_result(episode.get("execution_result"))
            line = (
                f"- {episode.get('user_command', '')}; "
                f"planner={domain}/{tool_name}; "
                f"result={result_text}"
            )
            if len("\n".join(lines + [line])) > hard_limit:
                break
            lines.append(line)

        summary = "\n".join(lines).strip()
        if len(summary) > hard_limit:
            summary = summary[: max(0, hard_limit - 3)].rstrip() + "..."
        _log_episodic("summary_generated", characters=len(summary), episodes=len(lines))
        return summary
    except Exception as exc:
        _log_episodic("memory_failure", action="summarize_recent_episodes", error=repr(exc))
        return ""
