"""Find a photo for an airport from Wikipedia (Wikimedia Commons images).

How it works: search Wikipedia for the airport's name, take the best match whose
title shares a distinctive word with the airport name, and use that page's
thumbnail. If anything is missing or doubtful we return None and the app shows a
plain placeholder - we never show a guessed or unrelated picture on purpose.
Wikipedia pictures are freely licensed; the app shows "Photo: Wikipedia".
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import requests

from .validation import _clean_airport_name, airport_info

API_URL = "https://en.wikipedia.org/w/api.php"
HEADERS = {"User-Agent": "AITravelAnalysis/1.0 (Streamlit app; airport photo lookup)"}
TIMEOUT_SECONDS = 6
GENERIC_WORDS = {
    "airport", "international", "intl", "regional", "municipal", "county", "domestic", "national",
    "airfield", "field", "airstrip", "aerodrome", "civil", "metropolitan", "memorial", "the", "and", "of",
}


def _distinctive_words(text: str) -> set:
    return {w for w in re.findall(r"[^\W\d_]{3,}", text.lower()) if w not in GENERIC_WORDS}


def _safe_image_url(url: Any) -> Optional[str]:
    if not isinstance(url, str):
        return None
    parsed = urlparse(url)
    if parsed.scheme == "https" and parsed.hostname == "upload.wikimedia.org":
        return url
    return None


def find_airport_photo(code: str) -> Optional[Dict[str, str]]:
    """Return {'url', 'page', 'title'} for the airport, or None. Never raises."""
    info = airport_info(code)
    if not info:
        return None
    name = _clean_airport_name(info.get("name", ""))
    if not name:
        return None
    keywords = _distinctive_words(name) or _distinctive_words(info.get("city", ""))
    if not keywords:
        return None
    params = {
        "action": "query", "format": "json", "generator": "search", "gsrsearch": name,
        "gsrlimit": 5, "prop": "pageimages", "piprop": "thumbnail", "pithumbsize": 700, "redirects": 1,
    }
    try:
        response = requests.get(API_URL, params=params, headers=HEADERS, timeout=TIMEOUT_SECONDS)
        response.raise_for_status()
        pages = (response.json().get("query") or {}).get("pages") or {}
    except (requests.exceptions.RequestException, ValueError):
        return None
    for page in sorted(pages.values(), key=lambda p: p.get("index", 99)):
        title = str(page.get("title", ""))
        url = _safe_image_url((page.get("thumbnail") or {}).get("source"))
        if url and keywords & _distinctive_words(title) and "airport" in title.lower():
            return {"url": url, "title": title, "page": "https://en.wikipedia.org/wiki/" + title.replace(" ", "_")}
    return None
