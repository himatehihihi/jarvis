from __future__ import annotations

import queue
import threading
import time
from collections import deque
from typing import Any, Callable, Deque, Dict, Optional

import numpy as np

from ai.live_session import GeminiLiveSessionBridge
from ai.live_tools import build_live_tool_declarations, execute_live_tool
from ai.provider import get_preferred_ai_provider, set_active_ai_provider
from audio.live_speaker import GeminiAudioSpeaker
from tools.common import structured_result

from . import DEFAULT_AUDIO_CONFIG, AudioConfig
from .microphone import MicrophoneStream
from .pipeline import AudioPipeline
from .vad import SileroVADDetector


LIVE_SYSTEM_PROMPT = """
You are Jarvis, a live voice assistant for a Windows desktop.
Be concise and natural in spoken replies.
Use tool calls when the user asks you to do something on the computer or with Jarvis capabilities.
Do not invent tool names.
If a tool requires confirmation and the call is rejected, ask the user for explicit confirmation before trying again.
If a tool fails, briefly explain the failure and continue helping.
""".strip()


class VoiceSystemController:
    """Gemini Live primary voice path with automatic local fallback."""

    def __init__(
        self,
        config: AudioConfig | None = None,
        *,
        local_pipeline: Optional[AudioPipeline] = None,
        primary_microphone: Optional[MicrophoneStream] = None,
        primary_speaker: Optional[GeminiAudioSpeaker] = None,
        primary_session_factory: Optional[Callable[..., GeminiLiveSessionBridge]] = None,
        vad_detector: Optional[SileroVADDetector] = None,
        time_fn: Optional[Callable[[], float]] = None,
    ):
        self.config = config or DEFAULT_AUDIO_CONFIG
        self.local_pipeline = local_pipeline or AudioPipeline(self.config)
        self.primary_microphone = primary_microphone or MicrophoneStream(self.config)
        self.primary_speaker = primary_speaker or GeminiAudioSpeaker(sample_rate=24000)
        self.primary_session_factory = primary_session_factory or GeminiLiveSessionBridge
        self.primary_session: Optional[GeminiLiveSessionBridge] = None
        self.primary_vad = vad_detector or SileroVADDetector(self.config)
        self.time_fn = time_fn or time.time

        self.primary_active = False
        self.local_active = False
        self.running = False
        self.primary_active_since = 0.0
        self.last_primary_success_at = 0.0
        self.last_primary_failure_at = 0.0
        self.last_fallback_started_at = 0.0
        self.minimum_reconnect_backoff_s = 5.0
        self.reconnect_backoff_s = self.minimum_reconnect_backoff_s
        self.max_reconnect_backoff_s = 60.0
        self.minimum_healthy_period_s = 5.0
        self.minimum_fallback_residence_s = 4.0
        self.probe_settle_s = 1.5
        self.last_reconnect_attempt = 0.0
        self._primary_probe_ready_until = 0.0
        self._state_lock = threading.Lock()
        self._starting_primary = False
        self._probing_primary = False

        self.monitor_thread: Optional[threading.Thread] = None
        self.primary_feed_thread: Optional[threading.Thread] = None
        self.primary_drain_thread: Optional[threading.Thread] = None
        self.stop_event = threading.Event()
        self.audio_test_queue: queue.Queue[Dict[str, Any]] = queue.Queue(maxsize=128)
        self.last_error = ""
        self.last_switch_reason = "startup"
        self.last_primary_event: Dict[str, Any] = {}
        self.last_primary_transcript = ""
        self.last_model_transcript = ""

        self._user_turn_active = False
        self._speaker_was_playing = False
        self._barge_in_frames = 0
        self._echo_floor_rms = 0.0
        self._turn_started_at = 0.0
        self._activity_serial = 0
        self._pre_roll_frames: Deque[np.ndarray] = deque()
        self._pre_roll_samples = max(int(self.config.pre_roll_s * self.config.sample_rate), self.config.sample_rate // 4)
        self._pre_roll_count = 0
        self._turn_audio_bytes = 0
        self._turn_rms_peak = 0.0

    def startup_validate(self) -> Dict[str, Any]:
        primary = {
            "preferred": get_preferred_ai_provider() == "gemini",
            "microphone": False,
            "speaker": True,
            "vad": False,
        }
        try:
            self.primary_microphone.start()
            primary["microphone"] = True
            self.primary_microphone.stop()
        except Exception as exc:
            primary["microphone_error"] = str(exc)
        primary["vad"] = self.primary_vad.load()
        return {"primary": primary, "fallback": {"available": True}}

    def start(self) -> bool:
        if self.running:
            return True
        self.running = True
        self.stop_event.clear()
        started_primary = self._start_primary(reason="startup")
        if not started_primary:
            self._start_local_fallback(reason="primary_unavailable_startup")
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True, name="jarvis-voice-monitor")
        self.monitor_thread.start()
        return True

    def stop(self) -> None:
        self.running = False
        self.stop_event.set()
        self._stop_primary()
        self._stop_local_fallback()

    def get_command(self, timeout: float = 0.2) -> Optional[str]:
        if not self.local_active:
            time.sleep(min(timeout, 0.2))
            return None
        return self.local_pipeline.get_command(timeout=timeout)

    def drain_commands(self) -> int:
        if self.local_active:
            return self.local_pipeline.drain_commands()
        return 0

    def get_test_event(self, timeout: float = 0.2) -> Optional[Dict[str, Any]]:
        try:
            return self.audio_test_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def mark_executing(self) -> None:
        if self.local_active:
            self.local_pipeline.mark_executing()

    def mark_passive(self) -> None:
        if self.local_active:
            self.local_pipeline.mark_passive()

    def diagnostics(self) -> Dict[str, Any]:
        microphone = self.primary_microphone.health() if self.primary_active else {}
        fallback_diag = self.local_pipeline.diagnostics() if self.local_active else {}
        session_health: Dict[str, Any] = {}
        if self.primary_session is not None and hasattr(self.primary_session, "health"):
            try:
                session_health = self.primary_session.health()
            except Exception:
                pass
        live_status = session_health.get("live_status") or (
            "connected" if self.primary_active else "fallback"
        )
        live_error = session_health.get("live_error") or self.last_error
        live_error_type = session_health.get("live_error_type", "")
        live_model = session_health.get("live_model", "")
        close_reason = session_health.get("close_reason", "")
        primary_diag = {
            "active": self.primary_active,
            "connected": self.primary_session is not None,
            "last_event": self.last_primary_event,
            "last_transcript": self.last_primary_transcript,
            "last_model_transcript": self.last_model_transcript,
            "last_error": live_error,
            "live_status": live_status,
            "live_error_type": live_error_type,
            "live_model": live_model,
            "close_reason": close_reason,
            "speaker": self.primary_speaker.health(),
            "user_turn_active": self._user_turn_active,
            "turn_audio_bytes": self._turn_audio_bytes,
            "turn_rms_peak": round(self._turn_rms_peak, 5),
            "echo_floor_rms": round(self._echo_floor_rms, 5),
        }
        return {
            "voice_mode": "gemini_primary" if self.primary_active else "local_fallback",
            "preferred_provider": get_preferred_ai_provider(),
            "live_status": live_status,
            "live_error": live_error,
            "live_error_type": live_error_type,
            "live_model": live_model,
            "close_reason": close_reason,
            "listening_active": self.primary_active or self.local_active,
            "assistant_state": "GEMINI_LIVE" if self.primary_active else fallback_diag.get("assistant_state", "PASSIVE_LISTENING"),
            "microphone": microphone or fallback_diag.get("microphone", {}),
            "vad": {
                "loaded": getattr(self.primary_vad, "loaded", False),
                "last_probability": round(getattr(self.primary_vad, "last_probability", 0.0), 4),
                "speech_events": getattr(self.primary_vad, "speech_events", 0),
            }
            if self.primary_active
            else fallback_diag.get("vad", {}),
            "wakeword": fallback_diag.get("wakeword", {}),
            "stt": fallback_diag.get("stt", {"loaded": False}),
            "queue_health": fallback_diag.get("queue_health", {}),
            "latency": fallback_diag.get("latency", {}),
            "transcription_failures": fallback_diag.get("transcription_failures", 0),
            "last_error": self.last_error or fallback_diag.get("last_error", ""),
            "primary": primary_diag,
            "fallback": fallback_diag,
            "last_switch_reason": self.last_switch_reason,
            "reconnect_backoff_s": self.reconnect_backoff_s,
        }

    def _monitor_loop(self) -> None:
        while not self.stop_event.is_set():
            if self.primary_active:
                event = self.primary_session.get_event(timeout=0.2) if self.primary_session is not None else None
                if event:
                    self.last_primary_event = event
                    self._push_event({"type": "primary_event", **event})
                    self._handle_primary_event(event)
                continue

            now = self.time_fn()
            if (
                self._primary_probe_ready_until > now
                and (now - self.last_fallback_started_at) >= self.minimum_fallback_residence_s
            ):
                if self._promote_primary(reason="primary_recovered"):
                    self.reconnect_backoff_s = self.minimum_reconnect_backoff_s
                    self._primary_probe_ready_until = 0.0
                    continue
            if get_preferred_ai_provider() == "gemini" and self._should_probe_primary(now):
                self.last_reconnect_attempt = now
                if self._probe_primary_ready():
                    self._primary_probe_ready_until = now + max(2.0, self.minimum_fallback_residence_s + 1.0)
                    if (now - self.last_fallback_started_at) >= self.minimum_fallback_residence_s:
                        if self._promote_primary(reason="primary_recovered"):
                            self.reconnect_backoff_s = self.minimum_reconnect_backoff_s
                            self._primary_probe_ready_until = 0.0
                    else:
                        self._push_event({"type": "primary_probe_ready_waiting", "fallback_age_s": round(now - self.last_fallback_started_at, 3)})
                else:
                    self._primary_probe_ready_until = 0.0
                    self.reconnect_backoff_s = min(
                        self.max_reconnect_backoff_s,
                        max(self.minimum_reconnect_backoff_s, self.reconnect_backoff_s * 2.0),
                    )
            time.sleep(0.2)

    def _handle_primary_event(self, event: Dict[str, Any]) -> None:
        event_type = str(event.get("type", ""))
        if event_type == "interrupted":
            self.primary_speaker.interrupt()
            if self.primary_session is not None:
                self.primary_session.clear_audio_queue()
            self._speaker_was_playing = False
            return
        if event_type == "turn_complete":
            self._speaker_was_playing = self.primary_speaker.is_playing()
            return
        if event_type == "error":
            self.last_error = str(event.get("error", "Gemini Live error"))
            close_reason = str(event.get("close_reason", "error"))
            print(f"[VOICE CONTROLLER] primary_error close_reason={close_reason} error={self.last_error}")
            self._switch_to_local("primary_session_error")
            return
        if event_type == "closed":
            close_reason = str(event.get("close_reason", ""))
            # Intentional stops are triggered by us — the session is already
            # being torn down. Do NOT switch to fallback; just clear state.
            if close_reason == "intentional":
                print(f"[VOICE CONTROLLER] primary_closed_intentional — no fallback switch")
                return
            # Remote or unknown close: genuine failure, switch to fallback.
            self.last_error = str(event.get("error", "Gemini Live remote close"))
            print(f"[VOICE CONTROLLER] primary_closed_unexpected close_reason={close_reason}")
            self._switch_to_local("primary_session_remote_close")

    def _should_probe_primary(self, now: float) -> bool:
        if self._probing_primary or self._starting_primary:
            return False
        if self.primary_active:
            return False
        return (now - self.last_reconnect_attempt) >= self.reconnect_backoff_s

    def _probe_primary_ready(self) -> bool:
        with self._state_lock:
            if self._probing_primary or self.primary_active:
                return False
            self._probing_primary = True
        probe = None
        try:
            probe = self.primary_session_factory(
                system_instruction=LIVE_SYSTEM_PROMPT,
                tool_handler=execute_live_tool,
                tools=build_live_tool_declarations(),
            )
            probe.start()
            started = self.time_fn()
            while (self.time_fn() - started) < self.probe_settle_s:
                event = probe.get_event(timeout=0.1)
                if event and event.get("type") == "error":
                    self.last_error = str(event.get("error", "primary probe failed"))
                    return False
                time.sleep(0.05)
            return True
        except Exception as exc:
            self.last_error = str(exc)
            return False
        finally:
            if probe is not None:
                try:
                    probe.stop()
                except Exception:
                    pass
            with self._state_lock:
                self._probing_primary = False

    def _promote_primary(self, reason: str) -> bool:
        self._stop_local_fallback()
        if self._start_primary(reason=reason):
            return True
        self._start_local_fallback(reason="primary_recovery_failed")
        return False

    def _start_primary(self, reason: str) -> bool:
        with self._state_lock:
            if self._starting_primary or self.primary_active:
                return self.primary_active
            self._starting_primary = True
        try:
            if get_preferred_ai_provider() != "gemini":
                set_active_ai_provider("ollama")
                return False
            self.primary_vad.load()
            self.primary_microphone.start()
            self.primary_speaker.start()
            self.primary_session = self.primary_session_factory(
                system_instruction=LIVE_SYSTEM_PROMPT,
                tool_handler=execute_live_tool,
                tools=build_live_tool_declarations(),
            )
            self.primary_session.start()
            self.primary_active = True
            self.primary_active_since = self.time_fn()
            self.last_switch_reason = reason
            self._reset_primary_turn_state()
            set_active_ai_provider("gemini")
            self.primary_feed_thread = threading.Thread(target=self._primary_feed_loop, daemon=True, name="jarvis-gemini-feed")
            self.primary_drain_thread = threading.Thread(target=self._primary_drain_loop, daemon=True, name="jarvis-gemini-drain")
            self.primary_feed_thread.start()
            self.primary_drain_thread.start()
            self.last_primary_success_at = self.time_fn()
            self._push_event({"type": "primary_started", "reason": reason})
            self._primary_probe_ready_until = 0.0
            return True
        except Exception as exc:
            self.last_error = str(exc)
            self._stop_primary()
            self.last_primary_failure_at = self.time_fn()
            return False
        finally:
            with self._state_lock:
                self._starting_primary = False

    def _stop_primary(self) -> None:
        self.primary_active = False
        session = self.primary_session
        self.primary_session = None
        if session is not None:
            try:
                session.stop()
            except Exception:
                pass
        self.primary_speaker.stop()
        self.primary_microphone.stop()
        self._reset_primary_turn_state()

    def _start_local_fallback(self, reason: str) -> None:
        if self.local_active:
            return
        self.local_pipeline.start()
        self.local_active = True
        self.last_switch_reason = reason
        self.last_fallback_started_at = self.time_fn()
        set_active_ai_provider("ollama")
        self._push_event({"type": "fallback_started", "reason": reason})

    def _stop_local_fallback(self) -> None:
        if not self.local_active:
            return
        self.local_pipeline.stop()
        self.local_active = False
        self._push_event({"type": "fallback_stopped"})

    def _switch_to_local(self, reason: str) -> None:
        now = self.time_fn()
        primary_age = now - self.primary_active_since if self.primary_active_since else 0.0
        self._stop_primary()
        self._start_local_fallback(reason=reason)
        self.last_primary_failure_at = now
        self.reconnect_backoff_s = (
            self.minimum_reconnect_backoff_s
            if primary_age >= self.minimum_healthy_period_s
            else min(
                self.max_reconnect_backoff_s,
                max(self.minimum_reconnect_backoff_s, self.reconnect_backoff_s * 2.0),
            )
        )

    def _primary_feed_loop(self) -> None:
        while self.running and self.primary_active and not self.stop_event.is_set():
            session = self.primary_session
            if session is None:
                break
            frame = self.primary_microphone.read(timeout=0.25)
            if frame is None:
                continue
            now = self.time_fn()
            self._remember_pre_roll(frame)
            is_speech, speech_start, speech_end = self.primary_vad.update(frame, now)
            speaker_playing = self.primary_speaker.is_playing()

            if self._primary_input_blocked(speaker_playing):
                continue

            if self._user_turn_active:
                self._send_turn_audio(frame, now)
                if speech_end:
                    self._end_user_turn()
                continue

            if speech_start or is_speech:
                if self._should_begin_user_turn(frame, is_speech=is_speech, speaker_playing=speaker_playing):
                    self._begin_user_turn(frame, now, barge_in=speaker_playing)
                continue

            if speaker_playing:
                self._update_echo_floor(frame)

    def _primary_drain_loop(self) -> None:
        while self.running and self.primary_active and not self.stop_event.is_set():
            session = self.primary_session
            if session is None:
                break
            transcript = session.get_transcript(timeout=0.1)
            if transcript is not None:
                self.last_primary_transcript = transcript.text
                if transcript.source == "model":
                    self.last_model_transcript = transcript.text
                    try:
                        from core import runtime

                        runtime.LAST_SPOKEN_TEXT = str(transcript.text or "").strip().lower()
                    except Exception:
                        pass
                self._push_event({"type": "transcript", "source": transcript.source, "text": transcript.text})
                print(f"[GEMINI LIVE] transcript source={transcript.source} text={transcript.text}")
            audio = session.get_audio(timeout=0.05)
            if audio:
                self.primary_speaker.play(audio)
                self._speaker_was_playing = True

    def _begin_user_turn(self, frame: np.ndarray, now: float, *, barge_in: bool) -> None:
        if self.primary_session is None:
            return
        if barge_in:
            self.primary_speaker.interrupt()
            self.primary_session.clear_audio_queue()
            self.primary_session.clear_transcript_queue()
            self._push_event({"type": "barge_in"})
        pre_roll = self._collect_pre_roll()
        initial = self._concat_audio(pre_roll, frame)
        try:
            self.primary_session.send_audio_chunk(initial, activity_start=True)
            self._user_turn_active = True
            self._turn_started_at = now
            self._turn_audio_bytes = len(initial)
            self._turn_rms_peak = max(self._turn_rms_peak, self._frame_rms(initial))
            self._activity_serial += 1
            self._barge_in_frames = 0
            self._speaker_was_playing = False
            self._push_event({"type": "user_turn_start", "activity_serial": self._activity_serial, "barge_in": barge_in})
        except Exception as exc:
            self.last_error = str(exc)
            self._switch_to_local("primary_turn_start_failed")

    def _send_turn_audio(self, frame: np.ndarray, now: float) -> None:
        if self.primary_session is None:
            return
        try:
            self.primary_session.send_audio_chunk(self._to_pcm16(frame))
            self._turn_audio_bytes += frame.size * 2
            self._turn_rms_peak = max(self._turn_rms_peak, self._frame_rms(frame))
        except Exception as exc:
            self.last_error = str(exc)
            self._switch_to_local("primary_send_audio_failed")

    def _end_user_turn(self) -> None:
        if self.primary_session is None:
            return
        try:
            self.primary_session.send_activity_end()
            self._push_event(
                {
                    "type": "user_turn_end",
                    "activity_serial": self._activity_serial,
                    "audio_bytes": self._turn_audio_bytes,
                    "rms_peak": round(self._turn_rms_peak, 5),
                }
            )
        except Exception as exc:
            self.last_error = str(exc)
            self._switch_to_local("primary_turn_end_failed")
        finally:
            self._user_turn_active = False
            self._turn_audio_bytes = 0
            self._turn_rms_peak = 0.0
            self._barge_in_frames = 0

    def _should_begin_user_turn(self, frame: np.ndarray, *, is_speech: bool, speaker_playing: bool) -> bool:
        if not is_speech:
            self._barge_in_frames = 0
            return False
        if not speaker_playing:
            return True
        rms = self._frame_rms(frame)
        self._update_echo_floor(frame)
        threshold = max(0.018, self._echo_floor_rms * 2.2)
        if rms >= threshold:
            self._barge_in_frames += 1
        else:
            self._barge_in_frames = 0
        return self._barge_in_frames >= 2

    def _primary_input_blocked(self, speaker_playing: bool) -> bool:
        try:
            from core import runtime

            if not runtime.cooldown_is_active():
                return False
            return not speaker_playing and not self._user_turn_active
        except Exception:
            return False

    def _remember_pre_roll(self, frame: np.ndarray) -> None:
        copied = np.asarray(frame, dtype=np.float32).copy()
        self._pre_roll_frames.append(copied)
        self._pre_roll_count += len(copied)
        while self._pre_roll_count > self._pre_roll_samples and self._pre_roll_frames:
            removed = self._pre_roll_frames.popleft()
            self._pre_roll_count -= len(removed)

    def _collect_pre_roll(self) -> list[np.ndarray]:
        return [chunk.copy() for chunk in self._pre_roll_frames]

    def _update_echo_floor(self, frame: np.ndarray) -> None:
        rms = self._frame_rms(frame)
        if self._echo_floor_rms <= 0.0:
            self._echo_floor_rms = rms
        else:
            self._echo_floor_rms = (self._echo_floor_rms * 0.92) + (rms * 0.08)

    def _reset_primary_turn_state(self) -> None:
        self._user_turn_active = False
        self._speaker_was_playing = False
        self._barge_in_frames = 0
        self._echo_floor_rms = 0.0
        self._turn_started_at = 0.0
        self._activity_serial = 0
        self._pre_roll_frames.clear()
        self._pre_roll_count = 0
        self._turn_audio_bytes = 0
        self._turn_rms_peak = 0.0

    def _push_event(self, event: Dict[str, Any]) -> None:
        try:
            self.audio_test_queue.put_nowait(event)
        except queue.Full:
            pass

    @staticmethod
    def _concat_audio(chunks: list[np.ndarray], current: np.ndarray) -> bytes:
        arrays = [np.asarray(chunk, dtype=np.float32) for chunk in chunks if chunk.size]
        arrays.append(np.asarray(current, dtype=np.float32))
        if not arrays:
            return b""
        joined = np.concatenate(arrays).astype(np.float32)
        return VoiceSystemController._to_pcm16(joined)

    @staticmethod
    def _frame_rms(frame: np.ndarray | bytes) -> float:
        if isinstance(frame, bytes):
            samples = np.frombuffer(frame, dtype=np.int16).astype(np.float32) / 32768.0
        else:
            samples = np.asarray(frame, dtype=np.float32)
        if samples.size == 0:
            return 0.0
        return float(np.sqrt(np.mean(np.square(samples))))

    @staticmethod
    def _to_pcm16(frame: np.ndarray) -> bytes:
        clipped = np.clip(frame, -1.0, 1.0)
        return (clipped * 32767.0).astype(np.int16).tobytes()


def voice_system_status(controller: VoiceSystemController) -> Dict[str, Any]:
    return structured_result(True, "voice_system_status", "Voice system status collected", **controller.diagnostics())
