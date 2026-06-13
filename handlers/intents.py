"""Intent handlers wired into IntentExecutor."""

from datetime import datetime

import hands
import mouth

from core.memory import (
    clear_tasks,
    forget_task,
    get_pending,
    load_memory,
    mark_done,
    remove_alarm,
    store_task,
)
from core.runtime import speak
from executor import IntentExecutor
from handlers.alarms import handle_alarm_command
from handlers.qa import handle_question
from handlers.stopwatch import handle_stopwatch_command
from tools.executor_router import execute_tool

active_alarm = None
alarm_active = False
EXECUTOR = None


def handle_stop_alarm_intent(intent):
    global alarm_active, active_alarm

    if alarm_active:
        alarm_active = False
        remove_alarm(active_alarm)
        active_alarm = None
        speak("Alarm stopped")
    else:
        speak("No alarm is active")
    return True


def intent_text(intent):
    return intent.get("text") or intent.get("raw_text") or ""


def text_handler(handler):
    def wrapped(intent):
        return handler(intent_text(intent))

    return wrapped


def handle_greeting_intent(intent):
    speak("Yes?")
    return True


def handle_voice_test_intent(intent):
    speak("This is Jarvis speaking")
    return True


def handle_voice_status_intent(intent):
    status = mouth.voice_status()
    print("VOICE STATUS:", status)
    if status.get("pyttsx3_installed"):
        speak("Voice package is installed")
    else:
        print("VOICE FIX: Try running: pip install pyttsx3 pywin32")
    return True


def handle_list_cached_apps_intent(intent):
    apps = hands.recent_apps()
    if not apps:
        speak("I do not have any cached apps yet")
        return True
    speak("Cached apps are " + ", ".join(apps[:8]))
    return True


def handle_list_whatsapp_contacts_intent(intent):
    contacts = hands.list_whatsapp_contacts()
    if not contacts:
        speak("I do not have WhatsApp contacts saved yet")
        return True
    speak("WhatsApp contacts are " + ", ".join(contacts[:8]))
    return True


def handle_list_open_apps_intent(intent):
    apps = hands.open_apps()
    if not apps:
        speak("I could not see any open apps")
        return True
    speak("Open apps include " + ", ".join(apps[:8]))
    return True


def handle_exit_intent(intent):
    speak("Jarvis offline")
    return "exit"


def handle_start_next_task_intent(intent):
    pending = get_pending()
    if not pending:
        speak("You have no tasks I can do right now")
        return True

    task = pending[0]["task"]
    speak(f"Doing {task}")
    if hands.run_action(task):
        mark_done(task)
    else:
        speak("I don't know how to do that yet")
    return True


def handle_time_intent(intent):
    speak(datetime.now().strftime("It is %I:%M %p"))
    return True


def handle_date_intent(intent):
    speak(datetime.now().strftime("Today is %A, %B %d"))
    return True


def handle_list_tasks_intent(intent):
    pending = [item for item in load_memory()["tasks"] if not item.get("done", False)]
    if not pending:
        speak("You have no tasks")
        return True

    speak("Here are your tasks")
    for index, task in enumerate(pending[:5], start=1):
        speak(f"{index}. {task.get('task')}")
    return True


def handle_clear_tasks_intent(intent):
    clear_tasks()
    speak("All tasks cleared")
    return True


def handle_store_task_intent(intent):
    task = intent.get("task", "")
    if not task:
        speak("Tell me the task")
        return True
    store_task(task)
    return True


def handle_add_task_intent(intent):
    task = intent.get("task", "")
    if not task:
        speak("Tell me the task")
        return True

    store_task(task)
    if intent.get("open_microsoft_todo"):
        speak("I added it locally, copied it, and opened Microsoft To Do")
        hands.open_microsoft_todo(task)
    return True


def handle_forget_task_intent(intent):
    task_text = intent.get("task", "")
    if forget_task(task_text):
        speak(f"Forgot {task_text}")
    else:
        speak("I could not find that task")
    return True


def handle_add_whatsapp_contact_intent(intent):
    name = intent.get("name", "")
    phone = intent.get("phone", "")
    if hands.add_whatsapp_contact(name, phone):
        speak(f"Saved WhatsApp contact {name}")
    else:
        speak("I could not save that contact")
    return True


def handle_match_whatsapp_contact_intent(intent):
    name = intent.get("name", "")
    contact = hands.find_whatsapp_contact(name)
    if contact:
        speak(f"Closest contact is {contact.get('name')}")
    else:
        speak("I could not match that to a saved contact")
    return True


def run_diagnostic_tool(tool_name):
    result = execute_tool(tool_name, {})
    if result.get("success"):
        speak(result.get("message", f"{tool_name} complete"))
    else:
        speak(result.get("error", f"{tool_name} failed"))
    return result


def handle_run_diagnostics_intent(intent):
    result = run_diagnostic_tool("run_full_diagnostics")
    recommendations = result.get("recommendations", []) if isinstance(result, dict) else []
    if recommendations:
        speak(f"Top recommendation: {recommendations[0]}")
    return result


def handle_check_ai_health_intent(intent):
    return run_diagnostic_tool("ai_health_check")


def handle_why_slow_intent(intent):
    result = run_diagnostic_tool("performance_report")
    latency = result.get("planner_latency_ms") if isinstance(result, dict) else None
    if latency is not None:
        speak(f"Planner latency is {latency} milliseconds")
    return result


def handle_recover_ai_intent(intent):
    return run_diagnostic_tool("recover_ai")


def handle_safe_mode_intent(intent):
    return run_diagnostic_tool("emergency_safe_mode")


def handle_check_memory_intent(intent):
    result = run_diagnostic_tool("memory_status")
    if isinstance(result, dict) and result.get("available_ram_gb") is not None:
        speak(f"Available RAM is {result.get('available_ram_gb')} gigabytes")
    return result


def get_executor():
    global EXECUTOR
    if EXECUTOR is None:
        EXECUTOR = IntentExecutor(
            speak,
            handlers={
                "stop_alarm": handle_stop_alarm_intent,
                "greeting": handle_greeting_intent,
                "voice_test": handle_voice_test_intent,
                "voice_status": handle_voice_status_intent,
                "list_cached_apps": handle_list_cached_apps_intent,
                "list_whatsapp_contacts": handle_list_whatsapp_contacts_intent,
                "list_open_apps": handle_list_open_apps_intent,
                "exit": handle_exit_intent,
                "start_next_task": handle_start_next_task_intent,
                "time": handle_time_intent,
                "date": handle_date_intent,
                "list_tasks": handle_list_tasks_intent,
                "clear_tasks": handle_clear_tasks_intent,
                "alarm_command": text_handler(handle_alarm_command),
                "stopwatch_command": text_handler(handle_stopwatch_command),
                "question_command": text_handler(handle_question),
                "store_task": handle_store_task_intent,
                "add_task": handle_add_task_intent,
                "forget_task": handle_forget_task_intent,
                "add_whatsapp_contact": handle_add_whatsapp_contact_intent,
                "match_whatsapp_contact": handle_match_whatsapp_contact_intent,
                "run_diagnostics": handle_run_diagnostics_intent,
                "check_ai_health": handle_check_ai_health_intent,
                "why_slow": handle_why_slow_intent,
                "recover_ai": handle_recover_ai_intent,
                "safe_mode": handle_safe_mode_intent,
                "check_memory": handle_check_memory_intent,
            },
        )
    return EXECUTOR
