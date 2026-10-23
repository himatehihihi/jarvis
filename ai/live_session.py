"""Experimental Gemini Live session bridge for streaming audio I/O."""

from __future__ import annotations

import asyncio
import queue
import threading
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

from google.genai import types

from .gemini_provider import DEFAULT_GEMINI_CONFIG, GeminiConfig, _client, build_live_connect_config


ToolHandler = Callable[[str, Dict[str, Any]], Dict[str, Any]]


@dataclass
class TranscriptEvent:
    source: str
    text: str


@dataclass
class SessionEvent:
    type: str
    payload: Dict[str, Any]


class GeminiLiveSessionBridge:
    """Background Live API session that accepts PCM audio and queues responses."""

    def __init__(
        self,
        system_instruction: str,
        tool_handler: Optional[ToolHandler] = None,
        tools: Optional[list[Any]] = None,
        config: Optional[GeminiConfig] = None,
    ):
        self.config = config or DEFAULT_GEMINI_CONFIG
        self.system_instruction = system_instruction
        self.tool_handler = tool_handler
        self.tools = tools or []
        self.audio_queue: queue.Queue[bytes] = queue.Queue(maxsize=256)
        self.transcript_queue: queue.Queue[TranscriptEvent] = queue.Queue(maxsize=256)
        self.event_queue: queue.Queue[Dict[str, Any]] = queue.Queue(maxsize=64)
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._ready = threading.Event()
        self._stop = threading.Event()
        self._session = None
        self._session_done = threading.Event()
        self._fatal_error = ""
        self._error_type = ""
        # idle | connecting | connected | failed | closing | closed
        self._live_status = "idle"
        self._close_reason = ""   # "intentional" | "remote" | "error" | ""

    # ------------------------------------------------------------------ #
    # Public properties                                                    #
    # ------------------------------------------------------------------ #

    @property
    def fatal_error(self) -> str:
        return self._fatal_error

    @property
    def error_type(self) -> str:
        return self._error_type

    @property
    def live_status(self) -> str:
        return self._live_status

    @property
    def live_model(self) -> str:
        return self.config.live_model

    @property
    def close_reason(self) -> str:
        return self._close_reason

    def health(self) -> Dict[str, Any]:
        return {
            "live_status": self._live_status,
            "live_model": self.config.live_model,
            "live_error": self._fatal_error,
            "live_error_type": self._error_type,
            "close_reason": self._close_reason,
        }

    # ------------------------------------------------------------------ #
    # Lifecycle                                                            #
    # ------------------------------------------------------------------ #

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._ready.clear()
        self._session_done.clear()
        self._fatal_error = ""
        self._error_type = ""
        self._close_reason = ""
        self._live_status = "connecting"
        print(f"[GEMINI LIVE] connect_attempt_starting model={self.config.live_model}")
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="jarvis-gemini-live"
        )
        self._thread.start()

        if not self._ready.wait(timeout=15):
            self._live_status = "failed"
            self._error_type = "TimeoutError"
            self._fatal_error = (
                f"Gemini Live session did not become ready within 15s "
                f"(model={self.config.live_model})"
            )
            print(f"[GEMINI LIVE] connect_failed type={self._error_type} error={self._fatal_error}")
            raise RuntimeError(self._fatal_error)

        if self._live_status == "failed":
            print(
                f"[GEMINI LIVE] connect_failed type={self._error_type} "
                f"error={self._fatal_error} model={self.config.live_model}"
            )
            raise RuntimeError(f"{self._error_type}: {self._fatal_error}")

        print(f"[GEMINI LIVE] connect_succeeded model={self.config.live_model}")

    def stop(self) -> None:
        """Intentional shutdown — does NOT emit an error/closed event to callers."""
        self._close_reason = "intentional"
        self._live_status = "closing"
        self._stop.set()
        if self._loop and self._session is not None:
            asyncio.run_coroutine_threadsafe(self._close_session(), self._loop)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

    # ------------------------------------------------------------------ #
    # Audio / text sending                                                 #
    # ------------------------------------------------------------------ #

    def send_audio_chunk(
        self,
        pcm16le_audio: bytes,
        *,
        activity_start: bool = False,
        activity_end: bool = False,
        end_of_turn: bool = False,
    ) -> None:
        kwargs: Dict[str, Any] = {}
        if pcm16le_audio:
            kwargs["audio"] = types.Blob(data=pcm16le_audio, mime_type="audio/pcm;rate=16000")
        if activity_start:
            kwargs["activity_start"] = types.ActivityStart()
        if activity_end:
            kwargs["activity_end"] = types.ActivityEnd()
        if end_of_turn:
            kwargs["audio_stream_end"] = True
        if not kwargs:
            return
        self._call_async(self._session.send_realtime_input(**kwargs))

    def send_activity_start(self) -> None:
        self._call_async(self._session.send_realtime_input(activity_start=types.ActivityStart()))

    def send_activity_end(self) -> None:
        self._call_async(self._session.send_realtime_input(activity_end=types.ActivityEnd()))

    def send_text(self, text: str) -> None:
        if not text:
            return
        self._call_async(self._session.send_realtime_input(text=text))

    # ------------------------------------------------------------------ #
    # Queue readers                                                        #
    # ------------------------------------------------------------------ #

    def get_audio(self, timeout: float = 0.1) -> Optional[bytes]:
        try:
            return self.audio_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def get_transcript(self, timeout: float = 0.1) -> Optional[TranscriptEvent]:
        try:
            return self.transcript_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def get_event(self, timeout: float = 0.1) -> Optional[Dict[str, Any]]:
        try:
            return self.event_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def clear_audio_queue(self) -> int:
        cleared = 0
        while True:
            try:
                self.audio_queue.get_nowait()
                cleared += 1
            except queue.Empty:
                break
        return cleared

    def clear_transcript_queue(self) -> int:
        cleared = 0
        while True:
            try:
                self.transcript_queue.get_nowait()
                cleared += 1
            except queue.Empty:
                break
        return cleared

    # ------------------------------------------------------------------ #
    # Internal async machinery                                             #
    # ------------------------------------------------------------------ #

    def _run_loop(self) -> None:
        asyncio.run(self._main())

    async def _main(self) -> None:
        self._loop = asyncio.get_running_loop()
        try:
            print(f"[GEMINI LIVE] building_client model={self.config.live_model}")
            client = _client(self.config)
            live_config = build_live_connect_config(
                self.system_instruction, config=self.config, tools=self.tools
            )
            print(f"[GEMINI LIVE] connecting model={self.config.live_model}")
            async with client.aio.live.connect(
                model=self.config.live_model, config=live_config
            ) as session:
                self._session = session
                self._live_status = "connected"
                print(f"[GEMINI LIVE] connected model={self.config.live_model}")
                self._ready.set()
                self._push_event({"type": "connected", "model": self.config.live_model})
                await self._receive_loop()
                # _receive_loop returned because _stop was set — intentional.
        except Exception as exc:
            self._live_status = "failed"
            self._error_type = type(exc).__name__
            self._fatal_error = str(exc)
            if not self._close_reason:
                self._close_reason = "error"
            print(
                f"[GEMINI LIVE] connect_failed type={self._error_type} "
                f"error={self._fatal_error} model={self.config.live_model}"
            )
            import traceback
            traceback.print_exc()
            self._push_event(
                {
                    "type": "error",
                    "error": self._fatal_error,
                    "error_type": self._error_type,
                    "close_reason": self._close_reason,
                }
            )
            self._ready.set()
        finally:
            if self._live_status == "connected":
                self._live_status = "closed"
                if not self._close_reason:
                    self._close_reason = "remote"
                print(
                    f"[GEMINI LIVE] session_closed model={self.config.live_model} "
                    f"reason={self._close_reason}"
                )
            self._session = None
            self._session_done.set()
            # Only emit "closed" if this was NOT an intentional stop.
            # Intentional stops are initiated by voice_controller calling .stop(),
            # which sets _stop before this finally runs.  The controller already
            # knows it is stopping — it does NOT need a "closed" event to trigger
            # any fallback logic.
            if self._close_reason != "intentional":
                self._push_event(
                    {
                        "type": "closed",
                        "close_reason": self._close_reason,
                        "error": self._fatal_error,
                    }
                )

    async def _receive_loop(self) -> None:
        """
        Keep reading from the session until _stop is set.

        The Gemini SDK's session.receive() is an async generator that yields
        server messages.  On an idle session it may exhaust between turns.
        We wrap it in an outer while loop so the bridge stays alive across
        quiet periods rather than exiting as soon as one receive() batch ends.
        """
        while not self._stop.is_set() and self._session is not None:
            received_any = False
            async for response in self._session.receive():
                if self._stop.is_set():
                    return
                received_any = True
                await self._handle_message(response)
            # If the inner async-for ended without _stop being set it means the
            # server closed the stream (remote disconnect / idle timeout).
            if not self._stop.is_set():
                if not self._close_reason:
                    self._close_reason = "remote"
                print(
                    f"[GEMINI LIVE] receive_loop_ended_unexpectedly "
                    f"received_any={received_any} reason={self._close_reason}"
                )
                return  # fall through to finally in _main → emits "closed"

    async def _handle_message(self, response: Any) -> None:
        vad_signal = getattr(response, "voice_activity_detection_signal", None)
        if vad_signal is not None:
            self._push_event(
                {
                    "type": "vad_signal",
                    "vad_signal_type": str(getattr(vad_signal, "vad_signal_type", "") or ""),
                }
            )
        voice_activity = getattr(response, "voice_activity", None)
        if voice_activity is not None:
            self._push_event(
                {
                    "type": "voice_activity",
                    "voice_activity_type": str(
                        getattr(voice_activity, "voice_activity_type", "") or ""
                    ),
                    "audio_offset": getattr(voice_activity, "audio_offset", None),
                }
            )

        content = getattr(response, "server_content", None)
        if content is not None:
            input_tx = getattr(content, "input_transcription", None)
            if input_tx and getattr(input_tx, "text", None):
                self._push_transcript("user", input_tx.text)
            output_tx = getattr(content, "output_transcription", None)
            if output_tx and getattr(output_tx, "text", None):
                self._push_transcript("model", output_tx.text)
            model_turn = getattr(content, "model_turn", None)
            parts = getattr(model_turn, "parts", None) or []
            for part in parts:
                inline = getattr(part, "inline_data", None)
                data = getattr(inline, "data", None) if inline is not None else None
                if data:
                    self._push_audio(bytes(data))
            if getattr(content, "interrupted", None):
                self._push_event({"type": "interrupted"})
            if getattr(content, "generation_complete", None):
                self._push_event({"type": "generation_complete"})
            if getattr(content, "turn_complete", None):
                self._push_event({"type": "turn_complete"})

        tool_call = getattr(response, "tool_call", None)
        function_calls = getattr(tool_call, "function_calls", None) or []
        if function_calls and self.tool_handler and self._session is not None:
            responses = []
            for fn in function_calls:
                name = str(getattr(fn, "name", "") or "")
                fn_id = str(getattr(fn, "id", "") or "")
                args = getattr(fn, "args", None) or {}
                result = self.tool_handler(name, dict(args))
                responses.append(
                    types.FunctionResponse(name=name, id=fn_id, response={"result": result})
                )
            await self._session.send_tool_response(function_responses=responses)

    async def _close_session(self) -> None:
        self._stop.set()

    def _call_async(self, coro: Any) -> None:
        if self._loop is None or self._session is None:
            raise RuntimeError("Gemini Live session is not connected")
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        future.result(timeout=5)

    def _push_audio(self, data: bytes) -> None:
        try:
            self.audio_queue.put_nowait(data)
        except queue.Full:
            pass

    def _push_transcript(self, source: str, text: str) -> None:
        try:
            self.transcript_queue.put_nowait(TranscriptEvent(source=source, text=str(text)))
        except queue.Full:
            pass

    def _push_event(self, event: Dict[str, Any]) -> None:
        try:
            self.event_queue.put_nowait(event)
        except queue.Full:
            pass
