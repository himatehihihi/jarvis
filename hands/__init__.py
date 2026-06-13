"""Hands package: machine actions grouped by domain."""

from hands.actions import can_handle, run_action
from hands.apps import (
    APP_ALIASES,
    APP_CACHE_FILE,
    open_app,
    open_apps,
    open_microsoft_todo,
    open_notepad,
    recent_apps,
)
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
from hands.common import clean_app_name, clean_task, copy_to_clipboard
from hands.input import (
    click,
    close_active_window,
    hotkey,
    move_mouse,
    open_from_start_search,
    press,
    press_key_command,
    switch_window,
    type_in_active_app,
    type_text,
)
from hands.media import normalize_media_platform, play_song
from hands.whatsapp import (
    add_whatsapp_contact,
    call_whatsapp_contact,
    find_whatsapp_contact,
    list_whatsapp_contacts,
    send_whatsapp_message,
)

__all__ = [
    "APP_ALIASES",
    "APP_CACHE_FILE",
    "SITE_ALIASES",
    "add_whatsapp_contact",
    "call_whatsapp_contact",
    "can_handle",
    "clean_app_name",
    "clean_task",
    "click",
    "close_active_window",
    "copy_to_clipboard",
    "find_whatsapp_contact",
    "hotkey",
    "list_whatsapp_contacts",
    "move_mouse",
    "normalize_media_platform",
    "open_app",
    "open_apps",
    "open_from_start_search",
    "open_google",
    "open_microsoft_todo",
    "open_notepad",
    "open_website",
    "open_youtube",
    "play_song",
    "press",
    "press_key_command",
    "recent_apps",
    "run_action",
    "search_google",
    "search_google_images",
    "search_google_maps",
    "search_youtube",
    "send_whatsapp_message",
    "switch_window",
    "type_in_active_app",
    "type_text",
]
