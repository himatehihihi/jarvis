from __future__ import annotations

import queue
import threading
import time
from enum import Enum
from typing import Any, Dict, Optional

import numpy as np

from . import DEFAULT_AUDIO_CONFIG, AudioConfig
from .audio_buffer import RollingAudioBuffer
from .cleanup import clean_transcript, is_echo_transcript, is_similar_transcript
from .microphone import MicrophoneStream
from .transcriber import FasterWhisperTranscriber
from .vad import SileroVADDetector
from .wakeword import OpenWakeWordDetector


class AssistantState(Enum):
    PASSIVE_LISTENING = "PASSIVE_LISTENING"
    ACTIVE_COMMAND_CAPTURE = "ACTIVE_COMMAND_CAPTURE"
    TRANSCRIBING = "TRANSCRIBING"
    EXECUTING = "EXECUTING"


class AudioPipeline:
    def __init__(self, config: AudioConfig | None = None):
        self.config = config or DEFAULT_AUDIO_CONFIG
        self.microphone = MicrophoneStream(self.config)
        self.vad = SileroVADDetector(self.config)
        self.wakeword = OpenWakeWordDetector(self.config)
        self.buffer = RollingAudioBuffer(self.config)
        self.transcriber: Optional[FasterWhisperTranscriber] = None
        self.running = False
        self.listening_active = False
        self.audio_thread: Optional[threading.Thread] = None
        self.stt_thread: Optional[threading.Thread] = None
        self.capture_queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=8)
        self.command_queue: queue.Queue[str] = queue.Queue(maxsize=16)
        self.audio_test_queue: queue.Queue[Dict[str, Any]] = queue.Queue(maxsize=32)
        self.stop_event = threading.Event()
        self.stt_busy = threading.Lock()
        self.interrupt_event = threading.Event()
        self.last_error = ""
        self.last_wake_latency_ms = 0.0
        self._wake_armed_at = 0.0
        self.command_deadline = 0.0
        self.command_speech_seen = False
        self.command_end_pending = False
        self.state = AssistantState.PASSIVE_LISTENING

    def _set_state(self, state: "AssistantState") -> None:
        if self.state != state:
            print(f"[AUDIO STATE] {self.state.value} -> {state.value}")
        self.state = state

    def startup_validate(self) -> Dict[str, Any]:
        status: Dict[str, Any] = {"microphone": False, "vad": False, "wakeword": False, "whisper": False}
        try:
            self.microphone.start()
            status["microphone"] = True
            self.microphone.stop()
        except Exception as exc:
            status["microphone_error"] = str(exc)
        status["vad"] = self.vad.load()
        status["wakeword"] = self.wakeword.load()
        try:
            self.transcriber = FasterWhisperTranscriber(self.config)
            status["whisper"] = True
        except Exception as exc:
            status["whisper_error"] = str(exc)
        return status

    def start(self) -> bool:
        if self.running:
            return True
        if self.transcriber is None:
            self.transcriber = FasterWhisperTranscriber(self.config)
        self.vad.load()
        self.wakeword.load()
        self.microphone.start()
        self.running = True
        self.listening_active = True
        self.stop_event.clear()
        self.audio_thread = threading.Thread(target=self._audio_loop, daemon=True, name="jarvis-audio-loop")
        self.stt_thread = threading.Thread(target=self._stt_loop, daemon=True, name="jarvis-stt-loop")
        self.audio_thread.start()
        self.stt_thread.start()
        return True

    def stop(self) -> None:
        self.running = False
        self.listening_active = False
        self.stop_event.set()
        self.microphone.stop()

    def get_command(self, timeout: float = 0.2) -> Optional[str]:
        try:
            return self.command_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def drain_commands(self) -> int:
        drained = 0
        while True:
            try:
                self.command_queue.get_nowait()
                drained += 1
            except queue.Empty:
                break
        if drained:
            print(f"[AUDIO DEBUG] drained_stale_commands count={drained}")
        return drained

    def get_test_event(self, timeout: float = 0.2) -> Optional[Dict[str, Any]]:
        try:
            return self.audio_test_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def _audio_loop(self) -> None:
        while not self.stop_event.is_set():
            frame = self.microphone.read(timeout=0.25)
            if frame is None:
                continue
            if self._input_suppressed():
                continue
            now = time.time()
            self.buffer.push(frame)

            is_speech, speech_start, speech_end = self.vad.update(frame, now)
            if speech_start:
                self._push_event({"type": "vad_start", "ts": now})
            if speech_end:
                self._push_event({"type": "vad_end", "ts": now})

            if self.state == AssistantState.PASSIVE_LISTENING:
                if self._input_suppressed():
                    continue

                detected, confidence = self.wakeword.detect(frame, now)
                if detected:
                    self._set_state(AssistantState.ACTIVE_COMMAND_CAPTURE)
                    self._wake_armed_at = now
                    self.command_deadline = now + self.config.command_timeout_s
                    self.command_speech_seen = False
                    self.command_end_pending = False
                    self.buffer.start_capture()
                    print("[WAKEWORD] detected")
                    print("[AUDIO] listening...")
                    print(f"[AUDIO DEBUG] command_capture_started deadline_s={self.config.command_timeout_s}")
                    self._push_event({"type": "wakeword", "confidence": confidence, "ts": now})
                continue

            if self.state == AssistantState.ACTIVE_COMMAND_CAPTURE:
                if speech_start:
                    self.command_speech_seen = True
                    print("[AUDIO DEBUG] speech_started_during_capture=true")

                if self.command_speech_seen and speech_end:
                    self.command_end_pending = True
                    print("[AUDIO DEBUG] speech_end_detected awaiting_post_roll=true")

                capture_timed_out = now >= self.command_deadline
                command_finished = False
                if self.command_end_pending:
                    command_finished = self.buffer.stop_speech_and_collect_post_roll(len(frame))
                no_speech_timeout = capture_timed_out and not self.command_speech_seen
                speech_timeout = capture_timed_out and self.command_speech_seen

                if command_finished or no_speech_timeout or speech_timeout:
                    reason = "speech_end_post_roll"
                    if no_speech_timeout:
                        reason = "timeout_no_speech"
                    elif speech_timeout:
                        reason = "timeout_after_speech"
                    print(f"[AUDIO DEBUG] command_capture_finalize reason={reason}")
                    print(f"[AUDIO DEBUG] command_capture_buffer_duration_s={self.buffer.captured_duration_s():.3f}")
                    audio = self.buffer.finalize_capture()
                    wake_latency = (time.time() - self._wake_armed_at) * 1000.0
                    self.last_wake_latency_ms = wake_latency
                    if self.command_speech_seen:
                        self._set_state(AssistantState.TRANSCRIBING)
                        print("[AUDIO] transcribing...")
                        self._queue_capture(audio)
                    else:
                        self._set_state(AssistantState.PASSIVE_LISTENING)
                    self.command_end_pending = False
                continue

    def _queue_capture(self, audio: np.ndarray) -> None:
        try:
            self.capture_queue.put_nowait(audio)
            duration_s = float(len(audio)) / float(self.config.sample_rate) if audio.size else 0.0
            print(f"[AUDIO DEBUG] transcription_queue_push samples={len(audio)} duration_s={duration_s:.3f} queue={self.capture_queue.qsize()}")
        except queue.Full:
            self.last_error = "capture_queue_full"
            print("[AUDIO DEBUG] transcription_queue_push_failed reason=capture_queue_full")

    def _stt_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                audio = self.capture_queue.get(timeout=0.25)
            except queue.Empty:
                continue
            duration_s = float(len(audio)) / float(self.config.sample_rate) if audio.size else 0.0
            print(f"[AUDIO DEBUG] transcription_queue_consume samples={len(audio)} duration_s={duration_s:.3f} queue={self.capture_queue.qsize()}")
            if audio.size == 0 or self.transcriber is None:
                print("[AUDIO DEBUG] stt_skip reason=empty_audio_or_transcriber_missing")
                self._set_state(AssistantState.PASSIVE_LISTENING)
                continue
            if duration_s < 0.35:
                print(f"[AUDIO DEBUG] stt_skip reason=audio_too_short duration_s={duration_s:.3f}")
                self._set_state(AssistantState.PASSIVE_LISTENING)
                continue
            if self._input_suppressed():
                print("[AUDIO DEBUG] stt_skip reason=input_suppressed")
                self._set_state(AssistantState.PASSIVE_LISTENING)
                continue
            if not self.stt_busy.acquire(blocking=False):
                print("[AUDIO DEBUG] stt_skip reason=stt_busy")
                self._set_state(AssistantState.PASSIVE_LISTENING)
                continue
            try:
                print("[AUDIO DEBUG] stt_worker_start")
                text, latency = self.transcriber.transcribe(audio)
                cleaned = clean_transcript(text, wake_word=self.config.wakeword_model_hint)
                self._push_event({"type": "transcript", "raw": text, "cleaned": cleaned, "latency_s": round(latency, 3)})
                if cleaned and not is_echo_transcript(cleaned):
                    try:
                        from core import runtime

                        if is_similar_transcript(cleaned, runtime.LAST_SPOKEN_TEXT):
                            print(f"[AUDIO DEBUG] stt_skip reason=similar_to_tts text={cleaned!r}")
                            cleaned = ""
                    except Exception:
                        pass
                if cleaned and not is_echo_transcript(cleaned):
                    print(f"[AUDIO] command recognized={cleaned}")
                    try:
                        self.command_queue.put_nowait(cleaned)
                    except queue.Full:
                        self.last_error = "command_queue_full"
                    if cleaned.strip() == "stop":
                        self.interrupt_event.set()
                elif cleaned:
                    print(f"[AUDIO DEBUG] stt_skip reason=echo_transcript text={cleaned!r}")
                self._set_state(AssistantState.PASSIVE_LISTENING)
            except Exception as exc:
                self.last_error = str(exc)
                print(f"[AUDIO DEBUG] stt_worker_error error={exc}")
                self._push_event({"type": "stt_error", "error": str(exc)})
                self._set_state(AssistantState.PASSIVE_LISTENING)
            finally:
                print("[AUDIO DEBUG] stt_worker_complete")
                self.stt_busy.release()

    def _push_event(self, event: Dict[str, Any]) -> None:
        try:
            self.audio_test_queue.put_nowait(event)
        except queue.Full:
            pass

    def diagnostics(self) -> Dict[str, Any]:
        stt_health = self.transcriber.health() if self.transcriber is not None else {"loaded": False}
        return {
            "listening_active": self.listening_active,
            "assistant_state": self.state.value,
            "microphone": self.microphone.health(),
            "vad": self.vad.health(),
            "wakeword": self.wakeword.health(),
            "stt": stt_health,
            "queue_health": {
                "capture_queue": self.capture_queue.qsize(),
                "command_queue": self.command_queue.qsize(),
                "audio_test_queue": self.audio_test_queue.qsize(),
            },
            "latency": {
                "wake_to_capture_ms": round(self.last_wake_latency_ms, 2),
                "stt_last_latency_s": stt_health.get("last_latency_s", 0.0),
            },
            "transcription_failures": stt_health.get("failures", 0),
            "last_error": self.last_error,
            "interrupt_ready": True,
        }

    def mark_executing(self) -> None:
        self._set_state(AssistantState.EXECUTING)
        self._suppress_input()

    def mark_passive(self) -> None:
        self._set_state(AssistantState.PASSIVE_LISTENING)

    def _input_suppressed(self) -> bool:
        try:
            from core import runtime

            return runtime.input_is_suppressed()
        except Exception:
            return self.state == AssistantState.EXECUTING

    def _suppress_input(self, extra_seconds: float | None = None) -> None:
        try:
            from core import runtime

            runtime.suppress_input(extra_seconds)
        except Exception:
            pass
