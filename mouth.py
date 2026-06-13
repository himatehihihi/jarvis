import os
import subprocess


VOICE_BACKEND = os.environ.get("JARVIS_VOICE_BACKEND", "pyttsx3").lower()
last_error = None

try:
    import pyttsx3
except Exception as e:
    pyttsx3 = None
    last_error = f"pyttsx3 import failed: {e}"


def set_error(message):
    global last_error
    last_error = message
    print("VOICE ERROR:", message.splitlines()[0] if message else "unknown voice error")


def speak_pyttsx3(text):
    if pyttsx3 is None:
        return False

    try:
        engine = pyttsx3.init("sapi5") if os.name == "nt" else pyttsx3.init()
        voices = engine.getProperty("voices")
        if voices:
            engine.setProperty("voice", voices[0].id)
        engine.setProperty("rate", 180)
        engine.setProperty("volume", 1.0)
        engine.say(str(text))
        engine.runAndWait()
        engine.stop()
        return True
    except Exception as e:
        set_error(f"pyttsx3 failed: {e}")
        return False


def ps_quote(text):
    return str(text).replace("'", "''")


def speak_windows(text):
    if os.name != "nt":
        return False

    script = (
        "Add-Type -AssemblyName System.Speech; "
        "$speaker = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        "$speaker.Volume = 100; "
        "$speaker.Rate = 0; "
        f"$speaker.Speak('{ps_quote(text)}')"
    )

    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=20,
        )
        if result.returncode == 0:
            return True
        set_error("Windows speech failed")
        return False
    except Exception as e:
        set_error(f"Windows speech exception: {e}")
        return False


def speak(text):
    backends = {
        "pyttsx3": [speak_pyttsx3, speak_windows],
        "windows": [speak_windows, speak_pyttsx3],
        "off": [],
    }.get(VOICE_BACKEND, [speak_pyttsx3, speak_windows])

    for backend in backends:
        if backend(text):
            return True

    if VOICE_BACKEND == "off":
        return True

    return False


def voice_status():
    return {
        "pyttsx3_installed": pyttsx3 is not None,
        "voice_backend": VOICE_BACKEND,
        "last_error": last_error,
    }
