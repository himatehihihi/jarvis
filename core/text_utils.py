"""Text parsing helpers for alarms, timers, and Q&A."""

import re
from datetime import datetime, timedelta


def human_duration(seconds):
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds} seconds"

    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        if seconds:
            return f"{minutes} minutes and {seconds} seconds"
        return f"{minutes} minutes"

    hours, minutes = divmod(minutes, 60)
    if minutes:
        return f"{hours} hours and {minutes} minutes"
    return f"{hours} hours"


def parse_duration(text):
    total = 0
    text = text.lower().replace("an ", "1 ").replace("a ", "1 ")
    matches = re.findall(
        r"(\d+(?:\.\d+)?)\s*(seconds?|secs?|minutes?|mins?|hours?|hrs?)",
        text,
    )

    for amount, unit in matches:
        amount = float(amount)
        if unit.startswith(("sec", "s")):
            total += amount
        elif unit.startswith(("min", "m")):
            total += amount * 60
        elif unit.startswith(("hour", "hr", "h")):
            total += amount * 3600

    return int(total) if total > 0 else None


def parse_alarm_time(text):
    text = text.lower()
    text = text.replace(".", ":")

    duration = parse_duration(text)
    if duration:
        return datetime.now() + timedelta(seconds=duration)

    match = re.search(r"\b(?:at\s*)?(\d{1,2}):(\d{2})\s*(am|pm)?", text)
    if not match:
        return None

    hour = int(match.group(1))
    minute = int(match.group(2))
    meridian = match.group(3)

    if meridian == "pm" and hour != 12:
        hour += 12
    elif meridian == "am" and hour == 12:
        hour = 0

    now = datetime.now()
    due = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

    if due <= now:
        due += timedelta(days=1)

    return due


def clean_question(text):
    text = text.strip().lower()
    text = re.sub(
        r"^(please\s+)?(tell me|answer|calculate|what is|what's|what was|who is|who's|how much is|define)\s+",
        "",
        text,
    )
    return text.strip(" ?")
