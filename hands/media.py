"""Media playback across platforms."""

import time
import webbrowser
from urllib.parse import quote_plus

from hands.apps import open_app
from hands.browser import search_youtube


def normalize_media_platform(platform):
    value = str(platform or "default").strip().lower()
    aliases = {
        "yt": "youtube",
        "youtube": "youtube",
        "youtube app": "youtube",
        "yt music": "youtube_music",
        "youtube music": "youtube_music",
        "youtube_music": "youtube_music",
        "spotify": "spotify",
        "spotify app": "spotify",
        "vlc": "vlc",
        "vlc player": "vlc",
        "default": "default",
    }
    return aliases.get(value, "default")


def _spotify_play(query):
    print(f"[MEDIA] handler=spotify query={query}")
    url = f"https://open.spotify.com/search/{quote_plus(query)}"
    webbrowser.open(url)
    time.sleep(1)
    return True


def _youtube_music_play(query):
    print(f"[MEDIA] handler=youtube_music query={query}")
    url = f"https://music.youtube.com/search?q={quote_plus(query)}"
    webbrowser.open(url)
    time.sleep(1)
    return True


def _youtube_play(query):
    print(f"[MEDIA] handler=youtube query={query}")
    return search_youtube(query)


def _vlc_play(query):
    print(f"[MEDIA] handler=vlc query={query}")
    if open_app("vlc"):
        return True
    return _youtube_play(query)


def play_song(query, platform="default"):
    query = str(query or "").strip()
    if not query:
        print("Jarvis: What should I play?")
        return False

    selected_platform = normalize_media_platform(platform)
    print(f"[MEDIA] selected_platform={selected_platform}")

    handlers = {
        "spotify": _spotify_play,
        "youtube_music": _youtube_music_play,
        "youtube": _youtube_play,
        "vlc": _vlc_play,
        "default": _youtube_play,
    }
    handler = handlers.get(selected_platform, _youtube_play)
    result = handler(query)
    print(f"[MEDIA] playback_status={'success' if result else 'failed'}")
    return result
