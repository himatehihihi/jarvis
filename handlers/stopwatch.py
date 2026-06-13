"""Stopwatch command handling."""

import time

from core.runtime import speak
from core.text_utils import human_duration

stopwatch_start = None
stopwatch_elapsed = 0


def handle_stopwatch_command(text, dry_run=False):
    global stopwatch_start, stopwatch_elapsed

    if "stopwatch" not in text:
        return False
    if dry_run:
        return True

    if "start" in text or "begin" in text:
        if stopwatch_start is None:
            stopwatch_start = time.time()
            speak("Stopwatch started")
        else:
            speak("Stopwatch is already running")
        return True

    if "stop" in text or "pause" in text:
        if stopwatch_start is not None:
            stopwatch_elapsed += time.time() - stopwatch_start
            stopwatch_start = None
            speak(f"Stopwatch stopped at {human_duration(stopwatch_elapsed)}")
        else:
            speak(f"Stopwatch is already stopped at {human_duration(stopwatch_elapsed)}")
        return True

    if "reset" in text or "clear" in text:
        stopwatch_start = None
        stopwatch_elapsed = 0
        speak("Stopwatch reset")
        return True

    if "status" in text or "time" in text or text == "stopwatch":
        elapsed = stopwatch_elapsed
        if stopwatch_start is not None:
            elapsed += time.time() - stopwatch_start
        speak(f"Stopwatch is at {human_duration(elapsed)}")
        return True

    return False
