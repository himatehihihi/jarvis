"""Unit tests for VoiceSystemController.
Runs fully offline — no real Gemini API, no real microphone.
7 tests covering: startup, failure fallback, event handling (interrupted /
error / intentional-close / remote-close), FakeSession.health() interface,
and diagnostics live_status passthrough.
"""
from __future__ import annotations

import queue
import sys
import types as _types
import unittest
from typing import Any, Dict
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Stub out every external package that voice_controller / live_session need
# so the tests run without a real Gemini SDK, sounddevice, torch, etc.
# ---------------------------------------------------------------------------
def _stub(name: str) -> MagicMock:
    mod = MagicMock()
    sys.modules[name] = mod
    return mod

for _pkg in [
    "google", "google.genai", "google.genai.types",
    "sounddevice",
    "numpy",
    "faster_whisper",
    "silero_vad",
    "torch",
    "onnxruntime",
    "openwakeword",
    "openwakeword.model",
    "openwakeword.utils",
    "tools", "tools.common", "tools.executor_router",
    "tools.tool_registry", "tools.tool_validator",
    "ai", "ai.live_session", "ai.live_tools", "ai.provider",
    "core", "core.runtime",
]:
    if _pkg not in sys.modules:
        _stub(_pkg)

# Make numpy behave just enough for the controller's static methods
import numpy as _np_real  # noqa: E402 – may fail, that's fine
try:
    import numpy as np  # real numpy if available
except ImportError:
    np = sys.modules["numpy"]

# Ensure google.genai.types.Blob / ActivityStart / ActivityEnd exist
_gtypes = sys.modules["google.genai.types"]
for _attr in ("Blob", "ActivityStart", "ActivityEnd", "FunctionResponse",
              "LiveConnectConfig", "SpeechConfig", "VoiceConfig",
              "PrebuiltVoiceConfig", "AudioTranscriptionConfig",
              "RealtimeInputConfig", "AutomaticActivityDetection",
              "ActivityHandling", "TurnCoverage", "HttpOptions",
              "GenerateContentConfig"):
    if not hasattr(_gtypes, _attr):
        setattr(_gtypes, _attr, MagicMock())

# tools.common.structured_result must be callable
sys.modules["tools.common"].structured_result = lambda ok, *a, **kw: {"ok": ok, **kw}


# ---------------------------------------------------------------------------
# Minimal stubs so the controller can be instantiated without real deps
# ---------------------------------------------------------------------------

class FakeAudioConfig:
    sample_rate = 16000
    channels = 1
    block_duration_ms = 80
    wake_threshold = 0.85
    wake_cooldown_s = 1.0
    vad_threshold = 0.45
    silence_timeout_s = 0.9
    pre_roll_s = 0.9
    post_roll_s = 0.25
    command_timeout_s = 8.0
    beam_size = 2
    temperature = 0.0
    transcription_timeout_s = 20.0
    wakeword_model_hint = "jarvis"
    whisper_model = "small.en"


class FakeMicrophone:
    def __init__(self):
        self.running = False
    def start(self): self.running = True
    def stop(self): self.running = False
    def read(self, timeout=0.5): return None
    def health(self): return {"running": self.running}


class FakeSpeaker:
    def __init__(self): self.playing = False; self.interruptions = 0
    def start(self): pass
    def stop(self): pass
    def play(self, _): self.playing = True
    def interrupt(self): self.playing = False; self.interruptions += 1
    def is_playing(self): return self.playing
    def health(self):
        return {"running": True, "playing": self.playing,
                "queued_chunks": 0, "interruptions": self.interruptions, "last_error": ""}


class FakeVAD:
    loaded = True
    last_probability = 0.0
    speech_events = 0
    def load(self): return True
    def update(self, frame, now): return False, False, False


class FakePipeline:
    def __init__(self): self._running = False
    def start(self): self._running = True
    def stop(self): self._running = False
    def get_command(self, timeout=0.2): return None
    def drain_commands(self): return 0
    def mark_executing(self): pass
    def mark_passive(self): pass
    def diagnostics(self):
        return {
            "assistant_state": "PASSIVE_LISTENING",
            "microphone": {}, "vad": {}, "wakeword": {},
            "stt": {"loaded": False}, "queue_health": {}, "latency": {},
            "transcription_failures": 0, "last_error": "",
            "listening_active": self._running,
        }


class FakeSession:
    """Offline stand-in for GeminiLiveSessionBridge.
    Implements the full health() interface required by VoiceSystemController.
    """

    def __init__(self, *, fail: bool = False):
        self._eq: queue.Queue = queue.Queue(maxsize=64)
        self._fail = fail
        self._live_status = "idle"
        self._live_error = ""
        self._live_error_type = ""
        self._close_reason = ""
        self._stopped = False

    # ---------- health() interface (required by controller.diagnostics) ----------

    def health(self) -> Dict[str, Any]:
        return {
            "live_status": self._live_status,
            "live_model": "test-model",
            "live_error": self._live_error,
            "live_error_type": self._live_error_type,
            "close_reason": self._close_reason,
        }

    # ---------- lifecycle ----------

    def start(self):
        if self._fail:
            self._live_status = "failed"
            self._live_error = "test failure"
            self._live_error_type = "RuntimeError"
            raise RuntimeError("test failure")
        self._live_status = "connected"
        self._eq.put({"type": "connected", "model": "test-model"})

    def stop(self):
        self._stopped = True
        self._close_reason = "intentional"
        self._live_status = "closed"
        # Intentional stop — no "closed" event emitted (matches real bridge)

    # ---------- queues ----------

    def get_event(self, timeout=0.1):
        try: return self._eq.get(timeout=timeout)
        except queue.Empty: return None

    def get_audio(self, timeout=0.05): return None
    def get_transcript(self, timeout=0.1): return None

    # ---------- sending ----------

    def send_audio_chunk(self, audio, **kwargs): pass
    def send_activity_start(self): pass
    def send_activity_end(self): pass
    def send_text(self, text): pass
    def clear_audio_queue(self): return 0
    def clear_transcript_queue(self): return 0

    # ---------- test helpers ----------

    def inject_event(self, event: Dict[str, Any]):
        self._eq.put(event)

    def inject_remote_close(self):
        self._live_status = "closed"
        self._close_reason = "remote"
        self._eq.put({"type": "closed", "close_reason": "remote", "error": ""})


# ---------------------------------------------------------------------------
# Factory helper
# ---------------------------------------------------------------------------

def _make_controller(fail_primary: bool = False):
    """Build a VoiceSystemController with all fakes injected."""
    from audio.voice_controller import VoiceSystemController

    sessions: list[FakeSession] = []

    def session_factory(**kwargs):
        s = FakeSession(fail=fail_primary)
        sessions.append(s)
        return s

    tick = [0.0]
    def time_fn():
        tick[0] += 0.01
        return tick[0]

    ctrl = VoiceSystemController(
        config=FakeAudioConfig(),
        local_pipeline=FakePipeline(),
        primary_microphone=FakeMicrophone(),
        primary_speaker=FakeSpeaker(),
        primary_session_factory=session_factory,
        vad_detector=FakeVAD(),
        time_fn=time_fn,
    )
    return ctrl, sessions


_PATCHES = dict(
    get_preferred=patch("audio.voice_controller.get_preferred_ai_provider", return_value="gemini"),
    set_active=patch("audio.voice_controller.set_active_ai_provider"),
    tools=patch("audio.voice_controller.build_live_tool_declarations", return_value=[]),
    executor=patch("audio.voice_controller.execute_live_tool", return_value={}),
)


def _start_primary(ctrl):
    with _PATCHES["get_preferred"], _PATCHES["set_active"], \
         _PATCHES["tools"], _PATCHES["executor"]:
        return ctrl._start_primary(reason="test")


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

class TestStartup(unittest.TestCase):

    def test_primary_starts_when_gemini_preferred(self):
        ctrl, sessions = _make_controller()
        ok = _start_primary(ctrl)
        self.assertTrue(ok)
        self.assertTrue(ctrl.primary_active)

    def test_primary_fails_gracefully_on_session_error(self):
        ctrl, sessions = _make_controller(fail_primary=True)
        ok = _start_primary(ctrl)
        self.assertFalse(ok)
        self.assertFalse(ctrl.primary_active)

    def test_local_fallback_starts_when_primary_fails(self):
        ctrl, sessions = _make_controller(fail_primary=True)
        _start_primary(ctrl)
        with patch("audio.voice_controller.set_active_ai_provider"):
            ctrl._start_local_fallback(reason="primary_unavailable_startup")
        self.assertTrue(ctrl.local_active)
        self.assertFalse(ctrl.primary_active)


class TestEventHandling(unittest.TestCase):

    def setUp(self):
        self.ctrl, self.sessions = _make_controller()
        _start_primary(self.ctrl)

    def test_interrupted_event_clears_speaker(self):
        self.ctrl.primary_speaker.playing = True
        self.ctrl._handle_primary_event({"type": "interrupted"})
        self.assertFalse(self.ctrl.primary_speaker.is_playing())

    def test_error_event_switches_to_fallback(self):
        with patch("audio.voice_controller.set_active_ai_provider"):
            self.ctrl._handle_primary_event({
                "type": "error",
                "error": "boom",
                "close_reason": "error",
            })
        self.assertFalse(self.ctrl.primary_active)
        self.assertTrue(self.ctrl.local_active)

    def test_intentional_closed_does_not_trigger_fallback(self):
        # Simulate what the bridge does when stop() is called:
        # emits NO "closed" event — but even if one arrives with
        # close_reason="intentional" the controller must ignore it.
        self.ctrl._handle_primary_event({
            "type": "closed",
            "close_reason": "intentional",
            "error": "",
        })
        self.assertFalse(self.ctrl.local_active,
                         "Intentional close must not activate local fallback")

    def test_remote_closed_switches_to_fallback(self):
        with patch("audio.voice_controller.set_active_ai_provider"):
            self.ctrl._handle_primary_event({
                "type": "closed",
                "close_reason": "remote",
                "error": "",
            })
        self.assertFalse(self.ctrl.primary_active)
        self.assertTrue(self.ctrl.local_active)


class TestSessionHealthInterface(unittest.TestCase):

    def test_fake_session_health_has_required_keys(self):
        s = FakeSession()
        h = s.health()
        for key in ("live_status", "live_model", "live_error", "live_error_type", "close_reason"):
            self.assertIn(key, h, f"health() missing key: {key}")

    def test_fake_session_connected_after_start(self):
        s = FakeSession()
        s.start()
        self.assertEqual(s.health()["live_status"], "connected")

    def test_diagnostics_live_status_from_session(self):
        ctrl, _ = _make_controller()
        _start_primary(ctrl)
        d = ctrl.diagnostics()
        self.assertEqual(d.get("live_status"), "connected",
                         "diagnostics() should report live_status=connected from session.health()")


if __name__ == "__main__":
    unittest.main(verbosity=2)
