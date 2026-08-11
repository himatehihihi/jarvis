from __future__ import annotations

import re
from difflib import SequenceMatcher


FILLER_WORDS = {
    "hey",
    "uh",
    "uhh",
    "um",
    "umm",
    "please",
    "like",
    "you know",
}

# Jarvis TTS phrases and common short Whisper hallucinations on noise/echo.
ECHO_PHRASES = {
    "",
    "doing it now",
    "doing it",
    "it now",
    "that did not work",
    "jarvis online",
    "jarvis offline",
    "jarvis ai online",
    "yes",
    "thank you",
    "thanks",
    "you",
    "bye",
    "stop",
}


def is_echo_transcript(text: str) -> bool:
    value = str(text or "").strip().lower()
    if not value:
        return True
    if value in ECHO_PHRASES:
        return True
    words = value.split()
    if len(words) <= 1 and len(value) < 4:
        return True
    return False


def is_similar_transcript(text: str, reference: str, threshold: float = 0.88) -> bool:
    value = clean_transcript(text)
    target = clean_transcript(reference)
    if not value or not target:
        return False
    if value == target:
        return True
    return SequenceMatcher(None, value, target).ratio() >= threshold


def clean_transcript(text: str, wake_word: str = "jarvis") -> str:
    value = str(text or "").strip().lower()
    if not value:
        return ""
    value = re.sub(rf"\b{re.escape(wake_word)}\b", " ", value)
    value = re.sub(r"[^\w\s]", " ", value)
    words = [w for w in value.split() if w not in FILLER_WORDS]

    deduped = []
    prev = None
    for word in words:
        if word == prev:
            continue
        deduped.append(word)
        prev = word
    value = " ".join(deduped)
    value = re.sub(r"\s+", " ", value).strip()
    return value
