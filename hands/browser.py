"""Web browsing and search actions."""

import time
import webbrowser
from urllib.parse import quote_plus, urlparse

from hands.common import clean_app_name

SITE_ALIASES = {
    "amazon": "https://www.amazon.com",
    "chatgpt": "https://chatgpt.com",
    "facebook": "https://www.facebook.com",
    "github": "https://github.com",
    "gmail": "https://mail.google.com",
    "instagram": "https://www.instagram.com",
    "maps": "https://maps.google.com",
    "netflix": "https://www.netflix.com",
    "reddit": "https://www.reddit.com",
    "spotify": "https://open.spotify.com",
    "twitter": "https://x.com",
    "wikipedia": "https://www.wikipedia.org",
    "x": "https://x.com",
}


def open_youtube():
    print("Jarvis: Opening YouTube...")
    webbrowser.open("https://youtube.com")
    return True


def search_youtube(query):
    if not query:
        print("Jarvis: What should I search on YouTube?")
        return False

    print("Jarvis: Searching YouTube...")
    webbrowser.open(f"https://www.youtube.com/results?search_query={quote_plus(query)}")
    time.sleep(1)
    return True


def open_google():
    print("Jarvis: Opening Google...")
    webbrowser.open("https://google.com")
    return True


def open_website(site):
    site = clean_app_name(site)
    if not site:
        print("Jarvis: What website should I open?")
        return False

    site = site.replace(" dot ", ".").replace(" ", "")
    url = SITE_ALIASES.get(site)
    if not url:
        parsed = urlparse(site if "://" in site else f"https://{site}")
        if "." in parsed.netloc:
            url = parsed.geturl()
        else:
            url = f"https://www.google.com/search?q={quote_plus(site)}"

    print(f"Jarvis: Opening {site}...")
    webbrowser.open(url)
    return True


def search_google(query):
    if not query:
        print("Jarvis: What should I search for?")
        return False

    print("Jarvis: Searching like a human...")
    webbrowser.open(f"https://www.google.com/search?q={quote_plus(query)}")
    time.sleep(1)
    return True


def search_google_images(query):
    if not query:
        print("Jarvis: What images should I search for?")
        return False

    print("Jarvis: Searching Google Images...")
    webbrowser.open(f"https://www.google.com/search?tbm=isch&q={quote_plus(query)}")
    time.sleep(1)
    return True


def search_google_maps(query):
    if not query:
        print("Jarvis: What place should I search for?")
        return False

    print("Jarvis: Searching Google Maps...")
    webbrowser.open(f"https://www.google.com/maps/search/{quote_plus(query)}")
    time.sleep(1)
    return True
