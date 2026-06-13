"""Keyboard, mouse, and window automation via pyautogui."""

import time

try:
    import pyautogui

    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.3
except Exception:
    pyautogui = None


def move_mouse(x, y):
    if pyautogui is None:
        return False
    pyautogui.moveTo(x, y, duration=0.5)
    return True


def click():
    if pyautogui is None:
        return False
    pyautogui.click()
    return True


def type_text(text):
    if pyautogui is None:
        return False
    pyautogui.write(text, interval=0.05)
    return True


def press(key):
    if pyautogui is None:
        return False
    pyautogui.press(key)
    return True


def hotkey(*keys):
    if pyautogui is None:
        return False
    pyautogui.hotkey(*keys)
    return True


def type_in_active_app(text):
    text = text.strip()
    if not text:
        print("Jarvis: What should I type?")
        return False
    if type_text(text):
        print("Jarvis: Typed it.")
        return True
    print("Jarvis: I cannot type without pyautogui.")
    return False


def press_key_command(key):
    key = key.strip().replace(" ", "")
    key_aliases = {
        "escape": "esc",
        "delete": "del",
        "spacebar": "space",
        "windows": "win",
        "control": "ctrl",
    }
    key = key_aliases.get(key, key)
    if press(key):
        print(f"Jarvis: Pressed {key}.")
        return True
    print("Jarvis: I cannot press keys without pyautogui.")
    return False


def close_active_window():
    if hotkey("alt", "f4"):
        print("Jarvis: Closed the active window.")
        return True
    print("Jarvis: I cannot close windows without pyautogui.")
    return False


def switch_window():
    if hotkey("alt", "tab"):
        print("Jarvis: Switched windows.")
        return True
    print("Jarvis: I cannot switch windows without pyautogui.")
    return False


def open_from_start_search(app_name):
    if pyautogui is None:
        return False

    pyautogui.press("win")
    time.sleep(0.5)
    pyautogui.write(app_name, interval=0.03)
    time.sleep(0.5)
    pyautogui.press("enter")
    return True
