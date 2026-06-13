import json
import sys
import time

from audio.cleanup import is_echo_transcript
from audio.pipeline import AudioPipeline
from audio.runtime import set_pipeline
from ai.qwen_brain import check_ollama_connection, plan_with_qwen, warmup_qwen_model
from core import runtime
from core.memory import add_episode, summarize_recent_episodes
from handlers.intents import get_executor
from intent_parser import clean_task, parse_intent
from tools.domain_router import route_plan
from tools.executor_router import execute_tool
from tools.tool_validator import canonicalize_planner_output, validate_planner_output

MUTE_COMMANDS = {"mute", "mute yourself", "stop listening"}
UNMUTE_COMMANDS = {"unmute", "wake up", "start listening"}
JARVIS_MUTED = False


def handle_chat_command(text, dry_run=False):
    intent = parse_intent(text)
    if dry_run:
        return intent.get("intent") != "unknown"
    return get_executor().execute(intent)


def debug_log(stage, payload):
    if not runtime.DEBUG_AI_PIPELINE:
        return
    try:
        printable = json.dumps(payload, ensure_ascii=True, indent=2)
    except Exception:
        printable = str(payload)
    print(f"[AI PIPELINE] {stage}:\n{printable}")


def _normalize_command_text(command):
    return clean_task(command).strip().lower()


def _is_mute_command(command):
    return _normalize_command_text(command) in MUTE_COMMANDS


def _is_unmute_command(command):
    return _normalize_command_text(command) in UNMUTE_COMMANDS


def run_ai_planner_pipeline(command, confirmed=False, execute=True):
    episodic_summary = summarize_recent_episodes(limit=5, max_chars=700)
    debug_log("episodic_summary", {"characters": len(episodic_summary), "summary": episodic_summary})
    planner_output = plan_with_qwen(
        command,
        timeout=runtime.AI_RUNTIME_TIMEOUT_SECONDS,
        episodic_summary=episodic_summary,
    )
    debug_log("planner_output", planner_output)

    routed_plan = route_plan(planner_output)
    debug_log("selected_domain", {"domain": routed_plan.get("domain"), "domain_valid": routed_plan.get("domain_valid")})
    canonical_plan = canonicalize_planner_output(routed_plan)
    debug_log("canonicalized_plan", canonical_plan)

    selected_tool = None
    tools = canonical_plan.get("tools") or []
    if tools and isinstance(tools[0], dict):
        selected_tool = tools[0].get("name")
    if not selected_tool:
        selected_tool = canonical_plan.get("tool")
    debug_log("selected_tool", {"tool": selected_tool})

    validation = validate_planner_output(canonical_plan, confirmed=confirmed)
    debug_log("validation_result", validation.to_dict())

    if not validation.ok:
        message = "I could not safely execute that request"
        if validation.errors:
            message = f"{message}: {validation.errors[0]}"
        if execute:
            runtime.speak(message)
            return False
        return {
            "ok": False,
            "error": message,
            "planner_output": planner_output,
            "routed_plan": canonical_plan,
            "validation": validation.to_dict(),
            "executor_payload": None,
        }

    executor_payload = validation.executor_intent or {"intent": "unknown", "raw_text": command}
    debug_log("executor_payload", executor_payload)

    if execute:
        execution_result = get_executor().execute(executor_payload)
        add_episode(command, planner_output, execution_result)
        return execution_result

    return {
        "ok": True,
        "planner_output": planner_output,
        "routed_plan": canonical_plan,
        "validation": validation.to_dict(),
        "executor_payload": executor_payload,
    }


def should_ignore_command(command):
    command = clean_task(command)
    return not command or is_echo_transcript(command)


def execute_command(command):
    global JARVIS_MUTED
    command = clean_task(command)
    if should_ignore_command(command):
        print(f"[AUDIO DEBUG] ignored_command={command!r}")
        return False
    if _is_unmute_command(command):
        if JARVIS_MUTED:
            JARVIS_MUTED = False
            runtime.speak("Listening again.")
        return True
    if _is_mute_command(command):
        if not JARVIS_MUTED:
            JARVIS_MUTED = True
            runtime.speak("Microphone muted.")
        return True
    if JARVIS_MUTED:
        print(f"[AUDIO DEBUG] muted_ignored_command={command!r}")
        return False

    deterministic_intent = parse_intent(command)
    if deterministic_intent.get("intent") != "unknown":
        if runtime.AUDIO_PIPELINE is not None:
            runtime.AUDIO_PIPELINE.mark_executing()
        print("[AUDIO] executing...")
        return get_executor().execute(deterministic_intent)

    try:
        if runtime.DIAGNOSTICS_STATE_FILE.exists():
            state = json.loads(runtime.DIAGNOSTICS_STATE_FILE.read_text(encoding="utf-8"))
            if state.get("safe_mode"):
                runtime.speak("Safe mode is enabled, using deterministic commands only")
                return False
    except Exception:
        pass

    if not runtime.AI_PLANNER_AVAILABLE:
        runtime.speak("AI planner is currently unavailable, using core commands only")
        return False

    try:
        if runtime.AUDIO_PIPELINE is not None:
            runtime.AUDIO_PIPELINE.mark_executing()
        print("[AUDIO] executing...")
        return run_ai_planner_pipeline(command, confirmed=False, execute=True)
    except Exception as exc:
        print(f"[AI PIPELINE] error: {exc}")
        retry_manager = get_executor().retry_manager
        context = {"intent": "planner_failure", "tool": "planner", "payload": {"command": command}}
        outcome = retry_manager.run_with_retry(
            context,
            lambda: run_ai_planner_pipeline(command, confirmed=False, execute=True),
        )
        if outcome.success:
            return outcome.final_result
        print("[RETRY] planner_retry_failed invoking recover_ai")
        execute_tool("recover_ai", {})
        runtime.speak("I could not process that safely right now")
        return False


def command_from_heard_text(text):
    return clean_task(text)


def initialize_ai_planner():
    print("[AI STARTUP] checking Ollama connection")
    connection = check_ollama_connection(timeout=8)
    print(f"[AI STARTUP] connection: {connection}")
    if not connection.get("ok"):
        print("[AI STARTUP] Warning: AI planner failed to start (connection check failed)")
        runtime.AI_PLANNER_AVAILABLE = False
        return False

    print(f"[AI STARTUP] warming model qwen2.5-coder:7b (timeout={runtime.AI_STARTUP_TIMEOUT_SECONDS}s)")
    warmup = warmup_qwen_model(timeout=runtime.AI_STARTUP_TIMEOUT_SECONDS)
    print(f"[AI STARTUP] warmup: {warmup}")
    if not warmup.get("ok"):
        print("[AI STARTUP] Warning: AI planner failed to start")
        runtime.AI_PLANNER_AVAILABLE = False
        return False

    runtime.AI_PLANNER_AVAILABLE = True
    runtime.speak("Jarvis AI online")
    return True


def initialize_audio_pipeline():
    runtime.AUDIO_PIPELINE = AudioPipeline()
    set_pipeline(runtime.AUDIO_PIPELINE)
    status = runtime.AUDIO_PIPELINE.startup_validate()
    print(f"[AUDIO STARTUP] validation={status}")
    if not status.get("microphone"):
        print("[AUDIO STARTUP] microphone unavailable")
    if not status.get("wakeword"):
        print("[AUDIO STARTUP] wakeword model unavailable")
    if not status.get("vad"):
        print("[AUDIO STARTUP] VAD model unavailable")
    if not status.get("whisper"):
        print("[AUDIO STARTUP] whisper model unavailable")
    try:
        runtime.AUDIO_PIPELINE.start()
        print("[AUDIO STARTUP] pipeline running")
        return True
    except Exception as exc:
        print(f"[AUDIO STARTUP] pipeline failed: {exc}")
        return False


def run_audio_test_mode():
    ok = initialize_audio_pipeline()
    print(f"[AUDIO TEST] startup_ok={ok}")
    print("[AUDIO TEST] listening for VAD/WAKEWORD/STT events. Ctrl+C to stop.")
    try:
        while True:
            if runtime.AUDIO_PIPELINE is None:
                time.sleep(0.2)
                continue
            event = runtime.AUDIO_PIPELINE.get_test_event(timeout=0.5)
            if event:
                print(f"[AUDIO TEST] {json.dumps(event, ensure_ascii=True)}")
            if int(time.time()) % 10 == 0:
                diag = runtime.AUDIO_PIPELINE.diagnostics()
                print(f"[AUDIO TEST] diagnostics={json.dumps(diag, ensure_ascii=True)}")
                time.sleep(1.0)
    except KeyboardInterrupt:
        print("\n[AUDIO TEST] stopped")
    finally:
        if runtime.AUDIO_PIPELINE is not None:
            runtime.AUDIO_PIPELINE.stop()


def main():
    runtime.speak("Jarvis online")
    initialize_audio_pipeline()
    if not initialize_ai_planner():
        runtime.speak("Warning: AI planner failed to start")

    while True:
        try:
            text = runtime.listen()

            if not text:
                time.sleep(0.2)
                continue

            command = command_from_heard_text(text)
            print(f"[AUDIO DEBUG] command_to_execute={command}")

            result = execute_command(command)
            if result == "exit":
                break
            if runtime.AUDIO_PIPELINE is not None:
                runtime.AUDIO_PIPELINE.drain_commands()
                runtime.AUDIO_PIPELINE.mark_passive()
            runtime.wait_for_listen_ready()

            time.sleep(0.2)

        except KeyboardInterrupt:
            runtime.speak("Jarvis offline")
            if runtime.AUDIO_PIPELINE is not None:
                runtime.AUDIO_PIPELINE.stop()
            break
        except Exception as e:
            print("Error:", e)
            time.sleep(1)


if __name__ == "__main__":
    if "--audio-test" in sys.argv:
        run_audio_test_mode()
        sys.exit(0)
    if "--planner-test" in sys.argv:
        print("Jarvis planner test mode")
        while True:
            try:
                command = input("You: ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not command:
                continue
            if command.lower() in {"exit", "quit"}:
                break

            deterministic = parse_intent(clean_task(command))
            print(f"Deterministic intent: {deterministic.get('intent')}")
            if deterministic.get("intent") != "unknown":
                print("Path: deterministic executor")
                result = get_executor().execute(deterministic)
                print(f"Execution result: {result}")
                continue

            print("Path: AI planner pipeline")
            try:
                preview = run_ai_planner_pipeline(command, confirmed=False, execute=False)
                print("Planner JSON:")
                print(json.dumps(preview.get("planner_output"), indent=2, ensure_ascii=True))
                tools = (preview.get("planner_output") or {}).get("tools") or []
                selected_tool = tools[0].get("name") if tools and isinstance(tools[0], dict) else None
                if not selected_tool:
                    selected_tool = (preview.get("planner_output") or {}).get("tool")
                print(f"Selected domain: {(preview.get('planner_output') or {}).get('domain')}")
                print(f"Selected tool: {selected_tool}")
                print("Final execution mapping:")
                print(json.dumps(preview.get("executor_payload"), indent=2, ensure_ascii=True))
                if preview.get("ok"):
                    run_now = input("Execute mapped intent? [y/N]: ").strip().lower() in {"y", "yes"}
                    if run_now:
                        result = get_executor().execute(preview["executor_payload"])
                        print(f"Execution result: {result}")
                else:
                    print(f"Validation failed: {preview.get('error')}")
            except Exception as exc:
                print(f"Planner pipeline error: {exc}")
        sys.exit(0)

    if "--text" in sys.argv:
        runtime.speak("Jarvis text mode")
        while True:
            try:
                command = input("You: ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            result = execute_command(command)
            if result == "exit":
                break
    else:
        main()
