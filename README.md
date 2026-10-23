# J.A.R.V.I.S.

J.A.R.V.I.S. is a Windows voice assistant built around a deterministic command system, an optional AI planner, and a resilient audio runtime. It is designed to keep useful local automation available even when an online AI capability is unavailable.

## What it does

- Runs a microphone-driven voice loop with wake-word detection, VAD, speech-to-text, echo filtering, and interruptible audio output.
- Uses Gemini Live as the preferred real-time voice session when configured and available.
- Automatically falls back to the local audio pipeline after a genuine Gemini Live failure.
- Keeps Gemini's text planner health separate from Gemini Live health. A planner outage must not by itself demote a healthy Live voice session.
- Handles deterministic commands locally before sending unknown requests through the planner.
- Validates planned tool calls before execution and routes tools through a central registry.
- Provides system, window, browser, filesystem, productivity, media, vision, communication, and diagnostic tool domains.
- Stores bounded episodic interaction history and exposes runtime diagnostics.

## Architecture

```text
Microphone
   |
   v
VoiceSystemController ---> GeminiLiveSessionBridge ---> Gemini Live
   |                              |
   |                              +--> shared live tool registry
   v
Local audio pipeline (fallback)

Text command --> deterministic intent parser
                  |
                  +--> local executor
                  |
                  +--> optional Gemini/Ollama planner
                           |
                           v
                    router -> validator -> executor
```

The main boundaries are:

- `audio/voice_controller.py`: primary/fallback voice state, reconnect behavior, VAD turn state, barge-in, and diagnostics.
- `ai/live_session.py`: Gemini Live connection, audio events, transcripts, and session health.
- `ai/gemini_provider.py`: Gemini planner configuration and Live connection configuration.
- `ai/live_tools.py`: exposes the existing registry to Gemini function calling.
- `ai/provider.py`: provider selection and optional planner warmup.
- `tools/`: registry, validation, domain routing, execution, retries, and diagnostics.
- `core/memory.py`: bounded episodic memory and recovery from malformed state.
- `main.py`: application startup and command loop.

## Requirements

The repository currently does not contain a generated `requirements.txt`. The runtime expects Python 3.10+ on Windows and the packages used by the imported modules, including:

- Google GenAI SDK (`google-genai`)
- NumPy
- the configured speech-to-text, VAD, wake-word, audio, and Windows automation libraries

Install the dependencies used by your local environment, then verify imports before starting the assistant. The bundled speech model files under `model/` are local runtime assets and may be large.

## Configuration

Set secrets in the process environment; do not commit them:

```powershell
$env:GEMINI_API_KEY = "your-key"
# GOOGLE_API_KEY is accepted as an alternative name.
```

Useful optional settings include the Gemini planner model and the provider preference. Inspect `ai/gemini_provider.py`, `ai/provider.py`, and `core/runtime.py` for the current environment-variable names and defaults.

## Running

From the repository root:

```powershell
python main.py
```

Useful verification modes:

```powershell
python main.py --planner-test
python main.py --audio-test
python -m unittest discover -s tests -v
```

`--planner-test` previews deterministic routing, planner output, validation, and the final executor mapping before optionally running a command. `--audio-test` exercises the voice pipeline and prints diagnostic events.

## Startup and health semantics

Startup reports the capabilities independently. In particular, these states are intentionally separate:

- `planner=available` or `planner=unavailable`
- `live=connected` or a Live failure state
- `voice_mode=gemini_primary` or `voice_mode=local_fallback`

Do not interpret an unavailable text planner as proof that Gemini Live is unavailable. Real Gemini Live connectivity requires a configured key and a successful `GeminiLiveSessionBridge.start()` result.

## Safety notes

Tool calls pass through validation and safety levels before execution. Destructive or privileged actions should remain confirmation-gated. Review `tools/tool_registry.py` and `tools/tool_validator.py` before adding a new tool or exposing one to Gemini Live.

## Tests

The test suite covers voice-controller startup/fallback behavior and episodic-memory behavior. Hardware-dependent microphone, speaker, wake-word, and real-key Gemini Live smoke tests require a configured Windows environment and are not guaranteed by the unit suite alone.

## Status

This is an active personal project. The architecture is functional but still evolving; dependency packaging, hardware portability, and full end-to-end Live verification are ongoing work.
