"""WhatsApp contacts and messaging."""

import json
import os
import re
import time
import webbrowser
from datetime import datetime
from difflib import SequenceMatcher
from urllib.parse import quote_plus

from hands.apps import open_app
from hands.common import copy_to_clipboard, now_iso, parse_time
from hands.input import hotkey, pyautogui

CONTACTS_CACHE_FILE = "contacts_cache.json"


def normalize_contact_name(name):
    name = str(name).lower().strip()
    name = re.sub(r"[^a-z0-9]+", " ", name)
    return re.sub(r"\s+", " ", name).strip()


def clean_phone(phone):
    return re.sub(r"\D+", "", str(phone))


def load_contacts():
    try:
        with open(CONTACTS_CACHE_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
            if isinstance(data, dict) and isinstance(data.get("contacts"), list):
                return data
    except Exception:
        pass
    return {"contacts": []}


def save_contacts(data):
    with open(CONTACTS_CACHE_FILE, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=2)


def add_whatsapp_contact(name, phone=None):
    name = str(name).strip()
    if not name:
        return False

    key = normalize_contact_name(name)
    data = load_contacts()
    phone = clean_phone(phone) if phone else None

    for contact in data["contacts"]:
        aliases = {normalize_contact_name(contact.get("name", "")), *contact.get("aliases", [])}
        if key in aliases:
            contact["name"] = contact.get("name") or name
            if phone:
                contact["phone"] = phone
            contact["last_used"] = now_iso()
            save_contacts(data)
            return True

    data["contacts"].append({
        "name": name,
        "aliases": [key],
        "phone": phone,
        "last_used": now_iso(),
    })
    save_contacts(data)
    return True


def contact_score(query, contact):
    query = normalize_contact_name(query)
    names = [contact.get("name", ""), *contact.get("aliases", [])]
    scores = []
    for name in names:
        key = normalize_contact_name(name)
        if not key:
            continue
        if query == key:
            scores.append(1.0)
        elif query in key or key in query:
            scores.append(0.92)
        elif len(query) >= 3 and SequenceMatcher(None, query, key.split()[0]).ratio() >= 0.70:
            scores.append(0.82)
        else:
            scores.append(SequenceMatcher(None, query, key).ratio())
    return max(scores) if scores else 0


def find_whatsapp_contact(name):
    data = load_contacts()
    best_contact = None
    best_score = 0
    for contact in data["contacts"]:
        score = contact_score(name, contact)
        if score > best_score:
            best_score = score
            best_contact = contact
    return best_contact if best_score >= 0.50 else None


def mark_contact_used(contact):
    data = load_contacts()
    key = normalize_contact_name(contact.get("name", ""))
    for saved in data["contacts"]:
        if normalize_contact_name(saved.get("name", "")) == key:
            saved["last_used"] = now_iso()
            save_contacts(data)
            return


def list_whatsapp_contacts(limit=10):
    data = load_contacts()
    contacts = data["contacts"]
    contacts.sort(key=lambda c: parse_time(c.get("last_used")) or datetime.min, reverse=True)
    return [contact.get("name", "unknown") for contact in contacts[:limit]]


def open_whatsapp():
    return open_app("whatsapp")


def open_whatsapp_link(url):
    try:
        os.startfile(url)
        return True
    except Exception:
        try:
            webbrowser.open(url)
            return True
        except Exception:
            return False


def activate_whatsapp_window():
    if pyautogui is None:
        return False

    try:
        windows = pyautogui.getWindowsWithTitle("WhatsApp")
    except Exception:
        windows = []

    if not windows:
        return False

    window = windows[0]
    try:
        if window.isMinimized:
            window.restore()
        window.activate()
        time.sleep(0.5)
        return True
    except Exception:
        return False


def wait_for_whatsapp_window(timeout=8):
    if pyautogui is None:
        return False

    end = time.time() + timeout
    while time.time() < end:
        if activate_whatsapp_window():
            return True
        time.sleep(0.5)
    return False


def whatsapp_window_bounds():
    if pyautogui is None:
        return None

    try:
        windows = pyautogui.getWindowsWithTitle("WhatsApp")
    except Exception:
        return None

    if not windows:
        return None

    window = windows[0]
    return window.left, window.top, window.width, window.height


def open_whatsapp_chat_by_search(name):
    if pyautogui is None:
        print("Jarvis: I need pyautogui to search WhatsApp contacts.")
        return False

    if not open_whatsapp():
        return False

    time.sleep(2)
    hotkey("ctrl", "n")
    time.sleep(0.4)
    copy_to_clipboard(name)
    hotkey("ctrl", "v")
    time.sleep(0.8)
    pyautogui.press("enter")
    time.sleep(1)
    return True


def resolve_whatsapp_name(name):
    contact = find_whatsapp_contact(name)
    if contact:
        mark_contact_used(contact)
        return contact.get("name", name), contact.get("phone")
    return name, None


def resolve_whatsapp_contact_with_phone(name):
    return resolve_whatsapp_name(name)


def open_whatsapp_chat_by_phone(phone):
    phone = clean_phone(phone)
    if not phone:
        return False

    url = f"whatsapp://send?phone={phone}"
    if not open_whatsapp_link(url):
        return False
    return wait_for_whatsapp_window()


def send_whatsapp_message(name, message):
    name = str(name).strip()
    message = str(message).strip()
    if not name or not message:
        print("Jarvis: Tell me who to message and what to say.")
        return False

    matched_name, phone = resolve_whatsapp_contact_with_phone(name)
    if not phone:
        matched_name = name
        print(f"Jarvis: Trying WhatsApp search for {matched_name}...")
        if not open_whatsapp_chat_by_search(matched_name):
            return False

        if pyautogui is None:
            print("Jarvis: I need pyautogui to send the message.")
            return False

        copy_to_clipboard(message)
        hotkey("ctrl", "v")
        time.sleep(0.2)
        pyautogui.press("enter")
        print(f"Jarvis: Sent WhatsApp message to {matched_name}.")
        return True

    print(f"Jarvis: Messaging {matched_name} on WhatsApp...")
    url = f"whatsapp://send?phone={phone}&text={quote_plus(message)}"
    if not open_whatsapp_link(url):
        return False

    wait_for_whatsapp_window()
    time.sleep(1)

    if pyautogui is not None:
        pyautogui.press("enter")
    print(f"Jarvis: Sent WhatsApp message to {matched_name}.")
    return True


def call_whatsapp_contact(name, video=False):
    name = str(name).strip()
    if not name:
        print("Jarvis: Tell me who to call.")
        return False

    matched_name, phone = resolve_whatsapp_contact_with_phone(name)
    if not phone:
        matched_name = name
        print(f"Jarvis: Trying WhatsApp search for {matched_name}...")
        if not open_whatsapp_chat_by_search(matched_name):
            return False

        if pyautogui is None:
            print("Jarvis: I need pyautogui to click the call button.")
            return False

        activate_whatsapp_window()
        time.sleep(1)
        bounds = whatsapp_window_bounds()
        if bounds:
            left, top, width, _ = bounds
            x = left + width - (170 if video else 125)
            y = top + 55
        else:
            width, _ = pyautogui.size()
            x = width - (170 if video else 125)
            y = 90

        pyautogui.click(x, y)
        print(f"Jarvis: Started {'video ' if video else ''}WhatsApp call with {matched_name}.")
        return True

    print(f"Jarvis: Opening WhatsApp chat for {matched_name}...")
    if not open_whatsapp_chat_by_phone(phone):
        print("Jarvis: I could not open that WhatsApp chat.")
        return False

    if pyautogui is None:
        print("Jarvis: I opened the chat, but I need pyautogui to click the call button.")
        return False

    wait_for_whatsapp_window()
    time.sleep(1.5)
    bounds = whatsapp_window_bounds()
    if bounds:
        left, top, width, _ = bounds
        x = left + width - (170 if video else 125)
        y = top + 55
    else:
        width, _ = pyautogui.size()
        x = width - (170 if video else 125)
        y = 90

    pyautogui.click(x, y)
    print(f"Jarvis: Started {'video ' if video else ''}WhatsApp call with {matched_name}.")
    return True
