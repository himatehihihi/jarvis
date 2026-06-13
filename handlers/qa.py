"""Question answering via math, DuckDuckGo, or web search."""

import json
import math
import re
import urllib.parse
import urllib.request

import hands

from core.runtime import speak
from core.text_utils import clean_question

MATH_OPERATORS = {
    "plus": "+",
    "minus": "-",
    "times": "*",
    "multiplied by": "*",
    "divided by": "/",
    "over": "/",
}


def solve_math_question(text):
    expression = clean_question(text)
    for word, symbol in MATH_OPERATORS.items():
        expression = expression.replace(word, symbol)

    expression = expression.replace("x", "*")
    if not re.fullmatch(r"[\d\s+\-*/().%]+", expression):
        return None

    try:
        result = eval(expression, {"__builtins__": {}}, {"sqrt": math.sqrt})
    except Exception:
        return None

    if isinstance(result, float) and result.is_integer():
        result = int(result)
    return str(result)


def ask_instant_answer(question):
    query = urllib.parse.urlencode({
        "q": question,
        "format": "json",
        "no_redirect": "1",
        "no_html": "1",
        "skip_disambig": "1",
    })
    url = f"https://api.duckduckgo.com/?{query}"

    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception:
        return None

    answer = data.get("Answer") or data.get("AbstractText")
    if answer:
        return answer

    related = data.get("RelatedTopics") or []
    for item in related:
        if isinstance(item, dict) and item.get("Text"):
            return item["Text"]

    return None


def handle_question(text, dry_run=False):
    if not re.match(r"^(what|who|when|where|why|how|define|calculate|tell me)", text):
        return False
    if dry_run:
        return True

    math_answer = solve_math_question(text)
    if math_answer is not None:
        speak(math_answer)
        return True

    question = clean_question(text)
    answer = ask_instant_answer(question)
    if answer:
        speak(answer[:350])
        return True

    speak("I do not know that yet, so I will search it")
    hands.search_google(question)
    return True
