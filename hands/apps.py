"""Windows app discovery, caching, and launching."""

import csv
import json
import os
import re
import subprocess
import time
import webbrowser
from datetime import datetime
from difflib import SequenceMatcher

from hands.browser import SITE_ALIASES
from hands.common import clean_app_name, now_iso, parse_time, copy_to_clipboard
from hands.input import open_from_start_search

APP_ALIASES = {
    "calculator": ["calc.exe", "calculator:"],
    "calc": ["calc.exe", "calculator:"],
    "settings": ["ms-settings:"],
    "camera": ["microsoft.windows.camera:"],
    "photos": ["ms-photos:"],
    "paint": ["mspaint.exe"],
    "cmd": ["cmd.exe"],
    "command prompt": ["cmd.exe"],
    "powershell": ["powershell.exe"],
    "explorer": ["explorer.exe"],
    "file explorer": ["explorer.exe"],
    "task manager": ["taskmgr.exe"],
    "control panel": ["control.exe"],
    "word": ["winword.exe"],
    "excel": ["excel.exe"],
    "powerpoint": ["powerpnt.exe"],
    "whatsapp": ["whatsapp://", "shell:AppsFolder\\5319275A.WhatsAppDesktop_cv1g1gvanyjgm!App"],
    "whats app": ["whatsapp://", "shell:AppsFolder\\5319275A.WhatsAppDesktop_cv1g1gvanyjgm!App"],
}

APP_CACHE_FILE = "apps_cache.json"


def normalize_app_key(name):
    name = os.path.splitext(str(name).lower().strip())[0]
    name = re.sub(r"[^a-z0-9]+", " ", name)
    return re.sub(r"\s+", " ", name).strip()


def load_app_cache():
    try:
        with open(APP_CACHE_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
            if not isinstance(data, dict) or "apps" not in data:
                return {"apps": {}}
            return data
    except Exception:
        return {"apps": {}}


def save_app_cache(cache):
    with open(APP_CACHE_FILE, "w", encoding="utf-8") as file:
        json.dump(cache, file, indent=2)


def cache_app(cache, name, target=None, source=None, mark_seen=False, mark_opened=False):
    key = normalize_app_key(name)
    if not key:
        return

    app = cache["apps"].setdefault(key, {"name": name, "aliases": []})
    app["name"] = app.get("name") or name

    if target:
        app["target"] = target
    elif source == "running_process" and app.get("source") == "running_process":
        app.pop("target", None)
    if source:
        app["source"] = source

    aliases = set(app.get("aliases", []))
    aliases.add(key)
    aliases.add(normalize_app_key(name))
    for noisy_word in ["root", "desktop", "app"]:
        cleaner_alias = normalize_app_key(key.replace(noisy_word, ""))
        if cleaner_alias:
            aliases.add(cleaner_alias)
    app["aliases"] = sorted(alias for alias in aliases if alias)

    if mark_seen:
        app["last_seen"] = now_iso()
    if mark_opened:
        app["last_opened"] = now_iso()
        app["last_seen"] = now_iso()


def app_search_paths():
    paths = []
    program_data = os.environ.get("PROGRAMDATA")
    app_data = os.environ.get("APPDATA")

    if program_data:
        paths.append(os.path.join(program_data, "Microsoft", "Windows", "Start Menu", "Programs"))
    if app_data:
        paths.append(os.path.join(app_data, "Microsoft", "Windows", "Start Menu", "Programs"))

    return [path for path in paths if os.path.isdir(path)]


def scan_start_menu_shortcuts():
    shortcuts = []
    for root_path in app_search_paths():
        for root, _, files in os.walk(root_path):
            for file_name in files:
                if file_name.lower().endswith((".lnk", ".url", ".appref-ms")):
                    path = os.path.join(root, file_name)
                    name = os.path.splitext(file_name)[0]
                    shortcuts.append((name, path))
    return shortcuts


def scan_windows_start_apps():
    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-StartApps | ConvertTo-Csv -NoTypeInformation",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=12,
        )
    except Exception:
        return []

    if result.returncode != 0:
        return []

    apps = []
    for row in csv.DictReader(result.stdout.splitlines()):
        name = row.get("Name")
        app_id = row.get("AppID")
        if name and app_id:
            apps.append((name, f"shell:AppsFolder\\{app_id}"))
    return apps


def running_process_names():
    try:
        result = subprocess.run(
            ["tasklist", "/fo", "csv", "/nh"],
            check=False,
            capture_output=True,
            text=True,
            timeout=8,
        )
    except Exception:
        return set()

    if result.returncode != 0:
        return set()

    processes = set()
    for row in csv.reader(result.stdout.splitlines()):
        if row:
            processes.add(normalize_app_key(row[0]))
    return processes


def running_process_targets():
    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-Process | Where-Object {$_.Path} | Select-Object ProcessName,Path | ConvertTo-Csv -NoTypeInformation",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return {}

    if result.returncode != 0:
        return {}

    targets = {}
    for row in csv.DictReader(result.stdout.splitlines()):
        name = normalize_app_key(row.get("ProcessName", ""))
        path = row.get("Path")
        if name and path:
            targets[name] = path
    return targets


def refresh_app_cache():
    cache = load_app_cache()
    for app in cache["apps"].values():
        target = app.get("target", "")
        if app.get("source") == "running_process" and target.endswith(".exe"):
            app.pop("target", None)

    processes = running_process_names()
    process_targets = running_process_targets()
    shortcuts = scan_start_menu_shortcuts()
    start_apps = scan_windows_start_apps()

    for name, path in shortcuts:
        cache_app(cache, name, target=path, source="shortcut")

    for name, target in start_apps:
        cache_app(cache, name, target=target, source="start_apps")

    for process in processes:
        cache_app(
            cache,
            process,
            target=process_targets.get(process),
            source="running_process",
            mark_seen=True,
        )
        for shortcut_name, shortcut_path in shortcuts:
            shortcut_key = normalize_app_key(shortcut_name)
            if (
                process == shortcut_key
                or process in shortcut_key
                or SequenceMatcher(None, process, shortcut_key).ratio() >= 0.78
            ):
                cache_app(
                    cache,
                    shortcut_name,
                    target=shortcut_path,
                    source="shortcut",
                    mark_seen=True,
                )
        for app_name, app_target in start_apps:
            app_key = normalize_app_key(app_name)
            if (
                process == app_key
                or process in app_key
                or app_key in process
                or SequenceMatcher(None, process, app_key).ratio() >= 0.72
            ):
                cache_app(
                    cache,
                    app_name,
                    target=app_target,
                    source="start_apps",
                    mark_seen=True,
                )

    save_app_cache(cache)
    return cache


def recent_app_score(app_name, app):
    names = [app.get("name", ""), *app.get("aliases", [])]
    return max(
        SequenceMatcher(None, app_name, normalize_app_key(name)).ratio()
        for name in names
        if name
    )


def find_cached_app(app_name):
    cache = refresh_app_cache()
    app_key = normalize_app_key(app_name)
    best_app = None
    best_score = 0

    for app in cache["apps"].values():
        if not app.get("target"):
            continue

        score = recent_app_score(app_key, app)
        if app_key in app.get("aliases", []):
            score = 1.0
        elif app_key and app_key in normalize_app_key(app.get("name", "")):
            score = max(score, 0.92)

        if score > best_score:
            best_score = score
            best_app = app

    return best_app if best_score >= 0.62 else None


def record_app_open(app_name, target):
    cache = load_app_cache()
    cache_app(cache, app_name, target=target, source="jarvis_opened", mark_opened=True)
    save_app_cache(cache)


def recent_apps(limit=10):
    cache = refresh_app_cache()
    apps = [
        app
        for app in cache["apps"].values()
        if app.get("target")
    ]

    def app_sort_time(app):
        return parse_time(app.get("last_opened")) or parse_time(app.get("last_seen")) or datetime.min

    apps.sort(key=app_sort_time, reverse=True)
    return [app.get("name", "unknown") for app in apps[:limit]]


def open_apps(limit=10):
    processes = sorted(running_process_names())
    return processes[:limit]


def shortcut_score(app_name, shortcut_path):
    shortcut_name = os.path.splitext(os.path.basename(shortcut_path))[0].lower()
    app_name = app_name.lower()

    if shortcut_name == app_name:
        return 1.0
    if app_name in shortcut_name:
        return 0.92
    if shortcut_name in app_name:
        return 0.88
    return SequenceMatcher(None, app_name, shortcut_name).ratio()


def find_app_shortcut(app_name):
    best_path = None
    best_score = 0

    for root_path in app_search_paths():
        for root, _, files in os.walk(root_path):
            for file_name in files:
                if not file_name.lower().endswith((".lnk", ".url", ".appref-ms")):
                    continue

                path = os.path.join(root, file_name)
                score = shortcut_score(app_name, path)
                if score > best_score:
                    best_score = score
                    best_path = path

    return best_path if best_score >= 0.62 else None


def try_start(target):
    try:
        os.startfile(target)
        return True
    except Exception:
        pass

    if str(target).lower().startswith("shell:appsfolder\\"):
        try:
            subprocess.Popen(
                ["explorer.exe", target],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except Exception:
            pass

    return False


def open_app(app_name):
    app_name = clean_app_name(app_name)
    if not app_name:
        print("Jarvis: What app should I open?")
        return False

    if app_name in ["whatsapp", "whats app"] and open_from_start_search("whatsapp"):
        record_app_open("whatsapp", None)
        print("Jarvis: Opening whatsapp from Start search...")
        return True

    if app_name in APP_ALIASES:
        for target in APP_ALIASES[app_name]:
            if try_start(target):
                record_app_open(app_name, target)
                print(f"Jarvis: Opening {app_name}...")
                return True

    cached_app = find_cached_app(app_name)
    if cached_app and cached_app.get("target") and try_start(cached_app["target"]):
        record_app_open(cached_app.get("name", app_name), cached_app["target"])
        print(f"Jarvis: Opening {cached_app.get('name', app_name)}...")
        return True

    cache = refresh_app_cache()
    cache_key = normalize_app_key(app_name)
    cached_without_target = any(
        cache_key in app.get("aliases", [])
        or cache_key == normalize_app_key(app.get("name", ""))
        or cache_key in normalize_app_key(app.get("name", ""))
        or any(cache_key in alias for alias in app.get("aliases", []))
        for app in cache["apps"].values()
    )
    if cached_without_target and open_from_start_search(app_name):
        record_app_open(app_name, None)
        print(f"Jarvis: Opening {app_name} from Start search...")
        return True

    print(f"Jarvis: I could not find {app_name} in the app cache.")
    return False


def open_notepad():
    print("Jarvis: Opening Notepad...")
    os.system("notepad")
    return True


def open_microsoft_todo(task=None):
    print("Jarvis: Opening Microsoft To Do...")
    if task:
        copy_to_clipboard(task)
    webbrowser.open("ms-to-do://")
    time.sleep(1)
    return True
