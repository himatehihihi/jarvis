"""Shared runtime state and speech helpers for the Jarvis main loop."""

import os
import time
from pathlib import Path

import mouth

IS_SPEAKING = False
AUDIO_PIPELINE = None
DEBUG_AI_PIPELINE = True
AI_PLANNER_AVAILABLE = False
AI_PLANNER_STATUS = {"available": False, "provider": "unknown", "reason": "not_initialized"}
AI_STARTUP_TIMEOUT_SECONDS = 90
AI_RUNTIME_TIMEOUT_SECONDS = 90
DIAGNOSTICS_STATE_FILE = Path("diagnostics_state.json").resolve()
POST_SPEECH_COOLDOWN_S = float(os.getenv("JARVIS_POST_SPEECH_COOLDOWN_S", "1.5"))
LAST_SPOKEN_TEXT = ""

last_heard_time = 0
input_suppressed_until = 0.0


def set_speaking(is_speaking: bool) -> None:
    global IS_SPEAKING
    IS_SPEAKING = bool(is_speaking)


def suppress_input(extra_seconds: float | None = None) -> None:
    global input_suppressed_until
    cooldown = POST_SPEECH_COOLDOWN_S if extra_seconds is None else extra_seconds
    input_suppressed_until = max(input_suppressed_until, time.time() + cooldown)


def input_is_suppressed() -> bool:
    return IS_SPEAKING or time.time() < input_suppressed_until


def cooldown_is_active() -> bool:
    return time.time() < input_suppressed_until


def wait_for_listen_ready(poll_s: float = 0.1) -> None:
    while input_is_suppressed():
        time.sleep(poll_s)


def speak(text):
    global LAST_SPOKEN_TEXT
    print("Jarvis:", text)
    LAST_SPOKEN_TEXT = str(text or "").strip().lower()
    set_speaking(True)
    try:
        mouth.speak(text)
    except Exception:
        print("VOICE ERROR: Jarvis could not speak this response")
    finally:
        set_speaking(False)
        suppress_input()


def listen():
    global last_heard_time

    if AUDIO_PIPELINE is None or input_is_suppressed():
        return None
    text = AUDIO_PIPELINE.get_command(timeout=0.2)
    if not text:
        return None
    text = text.lower().strip()
    last_heard_time = time.time()
    print("HEARD:", text)
    return text
