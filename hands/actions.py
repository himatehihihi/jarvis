"""Action routing for legacy task strings."""

from hands.apps import open_app, open_microsoft_todo, open_notepad
from hands.browser import (
    SITE_ALIASES,
    open_google,
    open_website,
    open_youtube,
    search_google,
    search_google_images,
    search_google_maps,
    search_youtube,
)
from hands.common import clean_app_name, clean_task
from hands import input as input_actions
from hands import whatsapp as whatsapp_actions


def can_handle(task):
    task = clean_task(task)
    return any(
        word in task
        for word in [
            "open",
            "launch",
            "start",
            "run",
            "youtube",
            "google",
            "notepad",
            "search",
            "microsoft to do",
            "todo",
            "type",
            "press",
            "close window",
            "close app",
            "switch window",
            "switch app",
            "whatsapp",
            "message",
            "call",
        ]
    )


def run_action(task):
    task = clean_task(task)

    if task.startswith("whatsapp message "):
        rest = task.replace("whatsapp message", "", 1).strip()
        if " saying " in rest:
            name, message = rest.split(" saying ", 1)
        elif " message " in rest:
            name, message = rest.split(" message ", 1)
        else:
            print("Jarvis: Say it like WhatsApp message name saying message.")
            return False
        return whatsapp_actions.send_whatsapp_message(name, message)

    if task.startswith("whatsapp video call "):
        name = task.replace("whatsapp video call", "", 1).strip()
        return whatsapp_actions.call_whatsapp_contact(name, video=True)

    if task.startswith("whatsapp call "):
        name = task.replace("whatsapp call", "", 1).strip()
        return whatsapp_actions.call_whatsapp_contact(name)

    if task.startswith(("type ", "write ")):
        text = task.replace("type", "", 1).replace("write", "", 1).strip()
        return input_actions.type_in_active_app(text)

    if task.startswith("press "):
        key = task.replace("press", "", 1).strip()
        return input_actions.press_key_command(key)

    if task in ["close window", "close app", "close current window", "close this app"]:
        return input_actions.close_active_window()

    if task in ["switch window", "switch app", "switch apps", "next window"]:
        return input_actions.switch_window()

    if "youtube" in task and "search" in task:
        query = task.replace("youtube", "", 1).replace("search", "", 1).strip()
        if query.startswith("for "):
            query = query[4:].strip()
        return search_youtube(query)

    if "image" in task and "search" in task:
        query = task.replace("images", "", 1).replace("image", "", 1).replace("search", "", 1).strip()
        if query.startswith("for "):
            query = query[4:].strip()
        return search_google_images(query)

    if "maps" in task and ("search" in task or "find" in task):
        query = task.replace("maps", "", 1).replace("search", "", 1).replace("find", "", 1).strip()
        if query.startswith("for "):
            query = query[4:].strip()
        return search_google_maps(query)

    if "youtube" in task:
        return open_youtube()

    if "microsoft to do" in task or "todo" in task or "to do" in task:
        return open_microsoft_todo()

    if "search" in task:
        query = task.replace("search", "", 1).strip()
        if query.startswith("for "):
            query = query[4:].strip()
        if query.startswith("google for "):
            query = query[11:].strip()
        elif query.startswith("google "):
            query = query[7:].strip()
        return search_google(query)

    if task.startswith(("look up ", "lookup ", "find ")):
        query = task.replace("look up", "", 1).replace("lookup", "", 1).replace("find", "", 1).strip()
        return search_google(query)

    if "google" in task:
        return open_google()

    if "notepad" in task:
        return open_notepad()

    if task.startswith(("open website ", "open site ", "go to ", "visit ")):
        site = task.replace("open website", "", 1).replace("open site", "", 1)
        site = site.replace("go to", "", 1).replace("visit", "", 1).strip()
        return open_website(site)

    if task.startswith(("open ", "launch ", "start ", "run ")):
        app_name = clean_app_name(task)
        if app_name in SITE_ALIASES or "." in app_name or " dot " in app_name:
            return open_website(app_name)
        return open_app(task)

    print("Jarvis: I don't know how to do that yet.")
    return False
