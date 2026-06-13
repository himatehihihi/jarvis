import json
import re
from pathlib import Path


PATTERNS_FILE = Path(__file__).with_name("patterns.json")
COMMANDS_FILE = Path(__file__).with_name("commands.json")


def load_pattern_config():
    with open(PATTERNS_FILE, "r") as file:
        config = json.load(file)

    required_lists = [
        "action_starters",
        "intent_patterns",
        "remember_patterns",
        "direct_action_patterns",
        "yes_words",
        "no_words",
    ]
    for key in required_lists:
        if not isinstance(config.get(key), list):
            raise ValueError(f"{PATTERNS_FILE.name} must define a list named {key}")

    return config


def load_command_config():
    with open(COMMANDS_FILE, "r") as file:
        config = json.load(file)

    if not isinstance(config.get("exact_commands"), dict):
        raise ValueError(f"{COMMANDS_FILE.name} must define exact_commands as an object")
    if not isinstance(config.get("keyword_commands"), list):
        raise ValueError(f"{COMMANDS_FILE.name} must define keyword_commands as a list")

    return config


PATTERN_CONFIG = load_pattern_config()
COMMAND_CONFIG = load_command_config()
ACTION_STARTERS = PATTERN_CONFIG["action_starters"]
INTENT_PATTERNS = PATTERN_CONFIG["intent_patterns"]
REMEMBER_PATTERNS = PATTERN_CONFIG["remember_patterns"]
DIRECT_ACTION_PATTERNS = PATTERN_CONFIG["direct_action_patterns"]
MAX_MULTI_STEP_INTENTS = 4


def structured_intent(intent, **slots):
    data = {"intent": intent}
    data.update({key: value for key, value in slots.items() if value is not None})
    return data


def clean_task(task):
    task = str(task).strip().lower()
    task = re.sub(r"^(please|to)\s+", "", task)
    return task


def clean_search_query(query):
    query = clean_task(query)
    if query.startswith("for "):
        query = query[4:].strip()
    if query.startswith("google for "):
        query = query[11:].strip()
    elif query.startswith("google "):
        query = query[7:].strip()
    return query


def strip_leading_noise(text):
    text = clean_task(text)
    words = text.split()
    if not words:
        return text

    for index, word in enumerate(words[:4]):
        if word in ACTION_STARTERS:
            return " ".join(words[index:])
        if word == "look" and index + 1 < len(words) and words[index + 1] == "up":
            return " ".join(words[index:])
        if word == "go" and index + 1 < len(words) and words[index + 1] == "to":
            return " ".join(words[index:])

    return text


def wants_time(text):
    return bool(re.search(r"\b(time|clock)\b", text)) and not re.search(r"\b(timer|stopwatch)\b", text)


def wants_date(text):
    return bool(re.search(r"\b(date|day|today)\b", text)) and not re.search(r"\bupdate\b", text)


def parse_task_intent(text):
    for pattern in REMEMBER_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return structured_intent("store_task", task=clean_task(match.group(1)))

    for pattern in INTENT_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return structured_intent("store_task", task=clean_task(match.group(1)))

    return None


def parse_configured_command(text, include_questions=True):
    for handler_name, phrases in COMMAND_CONFIG["exact_commands"].items():
        if text in phrases:
            return structured_intent(handler_name, text=text)

    if wants_time(text):
        return structured_intent("time", text=text)
    if wants_date(text):
        return structured_intent("date", text=text)

    for route in COMMAND_CONFIG["keyword_commands"]:
        handler_name = route.get("handler")
        if handler_name == "question" and not include_questions:
            continue
        keywords = route.get("keywords", [])
        if not isinstance(keywords, list):
            raise ValueError(f"keywords for {handler_name} must be a list")
        if any(re.search(pattern, text) for pattern in keywords):
            return structured_intent(f"{handler_name}_command", text=text)

    return None


def parse_question_command(text):
    return parse_configured_command(text, include_questions=True)


def parse_management_command(text):
    contact_match = re.search(
        r"\b(?:add|save)\s+(?:whatsapp\s+)?(?:contact\s+)?(.+?)\s+(?:with\s+number\s+|number\s+|phone\s+|as\s+)?(\+?\d[\d\s-]{6,})$",
        text,
    )
    if contact_match:
        return structured_intent(
            "add_whatsapp_contact",
            name=clean_task(contact_match.group(1)),
            phone=contact_match.group(2),
            text=text,
        )

    contact_match = re.search(r"\b(?:who\s+is\s+)?(?:closest\s+contact|match\s+contact)\s+(.+)", text)
    if contact_match:
        return structured_intent(
            "match_whatsapp_contact",
            name=clean_task(contact_match.group(1)),
            text=text,
        )

    forget_match = re.search(r"\bforget\s+(.+)", text)
    if forget_match:
        return structured_intent("forget_task", task=clean_task(forget_match.group(1)), text=text)

    todo_match = re.search(r"\b(?:add|create|set)\s+(?:a\s+)?(?:task|todo|to do)(?:\s+to microsoft to do)?(?:\s+for|\s+to)?\s+(.+)", text)
    if todo_match:
        task = clean_task(todo_match.group(1))
        return structured_intent(
            "add_task",
            task=task,
            open_microsoft_todo=("microsoft" in text or "to do" in text or "todo" in text),
            text=text,
        )

    return None


def normalize_direct_action(command, detail, match):
    if "message" in command and match.lastindex and match.lastindex >= 2:
        return structured_intent(
            "whatsapp_message",
            target=clean_task(match.group(1)),
            message=match.group(2).strip(),
        )
    if "video call" in command:
        return structured_intent("whatsapp_video_call", target=detail)
    if "call" in command:
        return structured_intent("whatsapp_call", target=detail)
    if "youtube" in command and "search" in command:
        query = detail
        if query.startswith("for "):
            query = query[4:].strip()
        return structured_intent("youtube_search", query=query)
    if "image" in command and "search" in command:
        return structured_intent("image_search", query=clean_search_query(detail.replace("images", "", 1).replace("image", "", 1)))
    if "maps" in command and ("search" in command or "find" in command):
        return structured_intent("maps_search", query=clean_search_query(detail.replace("maps", "", 1)))
    if any(word in command for word in ["go to", "visit", "website", "site"]):
        return structured_intent("open_website", target=detail)
    if "look up" in command or "lookup" in command or "find" in command:
        return structured_intent("web_search", query=clean_search_query(detail))
    if command.startswith(("type", "please type")):
        return structured_intent("type_text", text=detail)
    if command.startswith(("write", "please write")):
        return structured_intent("type_text", text=detail)
    if "press" in command:
        return structured_intent("press_key", key=detail)
    if command in ["close window", "close app", "close current window", "close this app"]:
        return structured_intent("close_window")
    if command in ["switch window", "switch app", "switch apps", "next window"]:
        return structured_intent("switch_window")
    if "search" in command or "google" in command:
        return structured_intent("web_search", query=clean_search_query(detail))
    if detail in ["youtube", "google", "notepad"] or detail in ["microsoft to do", "todo", "to do"]:
        return structured_intent("open_known_target", target=detail)
    return structured_intent("open_app", target=detail)


def parse_direct_action(text):
    text = strip_leading_noise(text)

    if text.startswith(("i should ", "i need to ", "i have to ", "i will ")):
        return None

    if text.startswith("do "):
        text = clean_task(text[3:])

    for pattern in DIRECT_ACTION_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            command = match.group(0).strip().lower()
            detail = clean_task(match.group(1)) if match.groups() else ""
            return normalize_direct_action(command, detail, match)

    return None


def parse_legacy_action_text(text):
    text = strip_leading_noise(text)

    if text.startswith("whatsapp message "):
        rest = text.replace("whatsapp message", "", 1).strip()
        if " saying " in rest:
            name, message = rest.split(" saying ", 1)
            return structured_intent("whatsapp_message", target=clean_task(name), message=message.strip())

    if text.startswith("whatsapp video call "):
        return structured_intent("whatsapp_video_call", target=clean_task(text.replace("whatsapp video call", "", 1)))

    if text.startswith("whatsapp call "):
        return structured_intent("whatsapp_call", target=clean_task(text.replace("whatsapp call", "", 1)))

    return parse_direct_action(text)


def split_multi_step_text(text):
    parts = [
        part.strip()
        for part in re.split(r"\s+(?:and then|then|and)\s+", text, maxsplit=MAX_MULTI_STEP_INTENTS - 1)
        if part.strip()
    ]
    return parts


def parse_single_intent(text):
    text = clean_task(text)
    if not text:
        return structured_intent("greeting", text=text)

    for parser in (
        lambda value: parse_configured_command(value, include_questions=False),
        parse_management_command,
        parse_direct_action,
        parse_task_intent,
        parse_question_command,
    ):
        intent = parser(text)
        if intent:
            intent.setdefault("raw_text", text)
            return intent

    return structured_intent("unknown", raw_text=text)


def parse_intent(text):
    text = clean_task(text)
    parts = split_multi_step_text(text)

    if len(parts) > 1:
        steps = [parse_single_intent(part) for part in parts[:MAX_MULTI_STEP_INTENTS]]
        if any(step.get("intent") == "unknown" for step in steps):
            return parse_single_intent(text)
        return structured_intent("multi_step", steps=steps, raw_text=text)

    return parse_single_intent(text)
