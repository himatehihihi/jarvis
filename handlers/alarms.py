"""Alarm and timer command handling."""

import re
from datetime import datetime, timedelta

from core.memory import get_alarms, remove_alarm, store_alarm
from core.runtime import speak
from core.text_utils import human_duration, parse_alarm_time, parse_duration


def handle_alarm_command(text, dry_run=False):
    if not re.search(r"\b(alarms?|timers?)\b", text):
        return False

    if dry_run:
        return True

    if text in ["list alarms", "show alarms", "list timers", "show timers"]:
        alarms = get_alarms()
        if not alarms:
            speak("You have no alarms or timers set")
            return True

        speak("Here are your alarms and timers")
        for alarm in alarms[:5]:
            due = datetime.fromisoformat(alarm["due"])
            speak(f"{alarm.get('label', 'alarm')} at {due.strftime('%I:%M %p')}")
        return True

    if text in ["clear alarms", "clear timers", "clear alarms and timers"]:
        alarms = list(get_alarms())
        for alarm in alarms:
            remove_alarm(alarm)
        speak("Alarms and timers cleared")
        return True

    if re.search(r"\b(remove|delete|cancel)\b", text):
        alarms = get_alarms()
        if not alarms:
            speak("You have no alarms to remove")
            return True

        alarm = alarms[-1]
        remove_alarm(alarm)
        speak("Alarm removed")
        return True

    if "timer" in text:
        duration = parse_duration(text)

        if not duration:
            speak("Tell me how long to set the timer")
            return True

        due = datetime.now() + timedelta(seconds=duration)
        store_alarm("timer", due, "timer")

        speak(f"Timer set for {human_duration(duration)}")
        return True

    if "alarm" in text:
        due = parse_alarm_time(text)

        if not due:
            speak("Tell me the time for the alarm")
            return True

        store_alarm("alarm", due, "alarm")
        speak(f"Alarm set for {due.strftime('%I:%M %p')}")
        return True

    return False
