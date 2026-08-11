import queue
import threading
import time
import unittest
from unittest import mock

import numpy as np

from ai.provider import set_active_ai_provider
from audio.voice_controller import VoiceSystemController


class FakeMicrophone:
    def __init__(self):
        self.running = False
        self.start_count = 0
        self.stop_count = 0
        self.frames = queue.Queue()

    def start(self):
        self.running = True
        self.start_count += 1
        return True

    def stop(self):
        self.running = False
        self.stop_count += 1

    def read(self, timeout=0.5):
        if not self.running:
            return None
        try:
            return self.frames.get(timeout=timeout)
        except queue.Empty:
            return None

    def health(self):
        return {
            "running": self.running,
            "queue_size": self.frames.qsize(),
            "start_count": self.start_count,
            "stop_count": self.stop_count,
        }

    def push(self, frame):
        self.frames.put(np.asarray(frame, dtype=np.float32))


class FakeVAD:
    def __init__(self):
        self.loaded = True
        self.last_probability = 0.0
        self.speech_events = 0
        self.events = queue.Queue()

    def load(self):
        self.loaded = True
        return True

    def update(self, frame, now):
        try:
            result = self.events.get_nowait()
        except queue.Empty:
            result = (False, False, False)
        self.last_probability = 0.9 if result[0] else 0.05
        if result[1]:
            self.speech_events += 1
        return result

    def push(self, is_speech, speech_start, speech_end):
        self.events.put((is_speech, speech_start, speech_end))


class FakeSpeaker:
    def __init__(self, sample_rate=24000):
        self.sample_rate = sample_rate
        self.running = False
        self.playing = False
        self.start_count = 0
        self.stop_count = 0
        self.interruptions = 0
        self.played = []

    def start(self):
        self.running = True
        self.start_count += 1

    def stop(self):
        self.running = False
        self.playing = False
        self.stop_count += 1

    def play(self, pcm16le_audio):
        self.played.append(pcm16le_audio)
        self.playing = True

    def interrupt(self):
        self.interruptions += 1
        self.playing = False

    def clear(self):
        return 0

    def is_playing(self):
        return self.playing

    def health(self):
        return {
            "running": self.running,
            "playing": self.playing,
            "interruptions": self.interruptions,
            "played_chunks": len(self.played),
        }


class FakeSession:
    def __init__(self, *args, **kwargs):
        self.started = False
        self.stopped = False
        self.audio_calls = []
        self.event_queue = queue.Queue()
        self.transcript_queue = queue.Queue()
        self.audio_queue = queue.Queue()
        self.clear_audio_calls = 0
        self.clear_transcript_calls = 0

    def start(self):
        self.started = True
        self.event_queue.put({"type": "connected", "model": "fake"})

    def stop(self):
        self.stopped = True

    def send_audio_chunk(self, pcm16le_audio, *, activity_start=False, activity_end=False, end_of_turn=False):
        self.audio_calls.append(
            {
                "bytes": pcm16le_audio,
                "activity_start": activity_start,
                "activity_end": activity_end,
                "end_of_turn": end_of_turn,
            }
        )

    def send_activity_end(self):
        self.audio_calls.append({"bytes": b"", "activity_start": False, "activity_end": True, "end_of_turn": False})

    def get_event(self, timeout=0.1):
        try:
            return self.event_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def get_transcript(self, timeout=0.1):
        try:
            return self.transcript_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def get_audio(self, timeout=0.1):
        try:
            return self.audio_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def clear_audio_queue(self):
        self.clear_audio_calls += 1
        while not self.audio_queue.empty():
            self.audio_queue.get_nowait()
        return 0

    def clear_transcript_queue(self):
        self.clear_transcript_calls += 1
        while not self.transcript_queue.empty():
            self.transcript_queue.get_nowait()
        return 0

    def inject_event(self, event):
        self.event_queue.put(event)


class SessionFactory:
    def __init__(self, plan):
        self.plan = list(plan)
        self.instances = []
        self.lock = threading.Lock()

    def __call__(self, *args, **kwargs):
        with self.lock:
            if not self.plan:
                behavior = "session"
            else:
                behavior = self.plan.pop(0)
        if behavior == "raise":
            raise RuntimeError("connect failed")
        session = FakeSession(*args, **kwargs)
        self.instances.append(session)
        return session


class FakeLocalPipeline:
    def __init__(self):
        self.running = False
        self.start_count = 0
        self.stop_count = 0

    def start(self):
        self.running = True
        self.start_count += 1
        return True

    def stop(self):
        self.running = False
        self.stop_count += 1

    def get_command(self, timeout=0.2):
        return None

    def drain_commands(self):
        return 0

    def mark_executing(self):
        return None

    def mark_passive(self):
        return None

    def diagnostics(self):
        return {
            "assistant_state": "PASSIVE_LISTENING",
            "microphone": {"running": self.running},
            "vad": {"loaded": True},
            "wakeword": {"loaded": True},
            "stt": {"loaded": True},
            "queue_health": {},
            "latency": {},
            "transcription_failures": 0,
            "last_error": "",
        }


class VoiceControllerTests(unittest.TestCase):
    def setUp(self):
        set_active_ai_provider(None)
        self.mic = FakeMicrophone()
        self.vad = FakeVAD()
        self.speaker = FakeSpeaker()
        self.local_pipeline = FakeLocalPipeline()
        self.pref_patch = mock.patch("audio.voice_controller.get_preferred_ai_provider", return_value="gemini")
        self.pref_patch.start()

    def tearDown(self):
        self.pref_patch.stop()
        set_active_ai_provider(None)

    def _make_controller(self, factory):
        controller = VoiceSystemController(
            local_pipeline=self.local_pipeline,
            primary_microphone=self.mic,
            primary_speaker=self.speaker,
            primary_session_factory=factory,
            vad_detector=self.vad,
        )
        controller.minimum_reconnect_backoff_s = 0.2
        controller.reconnect_backoff_s = 0.2
        controller.minimum_fallback_residence_s = 0.1
        controller.minimum_healthy_period_s = 0.0
        controller.probe_settle_s = 0.05
        return controller

    def _wait_until(self, predicate, timeout=2.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if predicate():
                return True
            time.sleep(0.05)
        return False

    def test_primary_failure_switches_to_local_fallback(self):
        factory = SessionFactory(["raise"])
        controller = self._make_controller(factory)
        try:
            controller.start()
            self.assertTrue(self._wait_until(lambda: controller.local_active))
            self.assertFalse(controller.primary_active)
            self.assertEqual(self.local_pipeline.start_count, 1)
        finally:
            controller.stop()

    def test_primary_recovers_and_switches_back_from_fallback(self):
        factory = SessionFactory(["raise", "session", "session"])
        controller = self._make_controller(factory)
        try:
            controller.start()
            self.assertTrue(self._wait_until(lambda: controller.local_active))
            self.assertTrue(self._wait_until(lambda: controller.primary_active and not controller.local_active, timeout=3.0))
            self.assertGreaterEqual(len(factory.instances), 2)
            self.assertEqual(self.local_pipeline.stop_count, 1)
        finally:
            controller.stop()

    def test_repeated_disconnect_reconnect_keeps_single_active_path(self):
        factory = SessionFactory(["session", "session", "session", "session", "session"])
        controller = self._make_controller(factory)
        try:
            controller.start()
            self.assertTrue(self._wait_until(lambda: controller.primary_active))
            first = factory.instances[0]
            first.inject_event({"type": "error", "error": "drop-1"})
            self.assertTrue(self._wait_until(lambda: controller.local_active and not controller.primary_active, timeout=2.0))
            self.assertTrue(self._wait_until(lambda: controller.primary_active and not controller.local_active, timeout=3.0))
            current = factory.instances[-1]
            current.inject_event({"type": "error", "error": "drop-2"})
            self.assertTrue(self._wait_until(lambda: controller.local_active and not controller.primary_active, timeout=2.0))
            self.assertTrue(self._wait_until(lambda: controller.primary_active and not controller.local_active, timeout=3.0))
            self.assertFalse(controller.local_active and controller.primary_active)
        finally:
            controller.stop()

    def test_gemini_speaking_user_interrupts_and_barge_in_starts_new_turn(self):
        factory = SessionFactory(["session"])
        controller = self._make_controller(factory)
        try:
            controller.start()
            self.assertTrue(self._wait_until(lambda: controller.primary_active))
            session = factory.instances[0]
            self.speaker.playing = True
            controller._echo_floor_rms = 0.01
            loud = np.ones(1600, dtype=np.float32) * 0.3
            self.vad.push(True, True, False)
            self.vad.push(True, False, False)
            self.mic.push(loud)
            self.mic.push(loud)
            self.assertTrue(self._wait_until(lambda: any(call.get("activity_start") for call in session.audio_calls), timeout=2.0))
            self.assertGreaterEqual(self.speaker.interruptions, 1)
            self.assertGreaterEqual(session.clear_audio_calls, 1)
        finally:
            controller.stop()

    def test_playback_echo_does_not_start_user_turn(self):
        factory = SessionFactory(["session"])
        controller = self._make_controller(factory)
        try:
            controller.start()
            self.assertTrue(self._wait_until(lambda: controller.primary_active))
            session = factory.instances[0]
            self.speaker.playing = True
            controller._echo_floor_rms = 0.04
            quiet = np.ones(1600, dtype=np.float32) * 0.03
            self.vad.push(True, True, False)
            self.vad.push(True, False, False)
            self.mic.push(quiet)
            self.mic.push(quiet)
            time.sleep(0.5)
            self.assertFalse(any(call.get("activity_start") for call in session.audio_calls))
        finally:
            controller.stop()

    def test_clean_shutdown_stops_primary_resources(self):
        factory = SessionFactory(["session"])
        controller = self._make_controller(factory)
        controller.start()
        self.assertTrue(self._wait_until(lambda: controller.primary_active))
        session = factory.instances[0]
        controller.stop()
        self.assertFalse(controller.running)
        self.assertTrue(session.stopped)
        self.assertFalse(self.mic.running)
        self.assertFalse(self.speaker.running)

    def test_planner_failure_does_not_demote_live_primary(self):
        factory = SessionFactory(["session"])
        controller = self._make_controller(factory)
        try:
            controller.start()
            self.assertTrue(self._wait_until(lambda: controller.primary_active))
            self.assertFalse(controller.local_active)
            self.assertEqual(controller.diagnostics().get("voice_mode"), "gemini_primary")
        finally:
            controller.stop()


if __name__ == "__main__":
    unittest.main()
