"""Shared text and clipboard helpers."""

import re
from datetime import datetime


def clean_task(task):
    task = task.lower().strip()
    starters = [
        "jarvis ",
        "please ",
        "can you ",
        "could you ",
        "would you ",
        "will you ",
    ]

    changed = True
    while changed:
        changed = False
        for starter in starters:
            if task.startswith(starter):
                task = task[len(starter):].strip()
                changed = True

    return task


def clean_app_name(name):
    name = clean_task(name)
    prefixes = ["open ", "launch ", "start ", "run "]
    changed = True
    while changed:
        changed = False
        for prefix in prefixes:
            if name.startswith(prefix):
                name = name[len(prefix):].strip()
                changed = True
    return name


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def parse_time(value):
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


def copy_to_clipboard(text):
    try:
        import tkinter

        root = tkinter.Tk()
        root.withdraw()
        root.clipboard_clear()
        root.clipboard_append(text)
        root.update()
        root.destroy()
        return True
    except Exception:
        return False
