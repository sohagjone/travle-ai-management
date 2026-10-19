"""Find a photo for an airport. Several sources are tried in order:

1. Wikipedia article search (freely licensed pictures)
2. Wikipedia page summary by exact title
3. Google Images through SerpAPI (needs SERPAPI_API_KEY; costs 1 SerpAPI search,
   and results are cached by the app so it happens once per airport)

If every source fails we return None and the app shows a clean placeholder. A
photo is accepted only when its page/title shares a distinctive word with the
airport name, so we never show an unrelated picture on purpose.
Every failure is written to the log (with the HTTP status) to make problems easy to diagnose.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional
from urllib.parse import quote, urlparse

import requests

from .config import logger, redact
from .serp_client import ProviderError, serpapi_search
from .validation import _clean_airport_name, airport_info

WIKI_API = "https://en.wikipedia.org/w/api.php"
WIKI_SUMMARY = "https://en.wikipedia.org/api/rest_v1/page/summary/"
# Wikimedia asks for a descriptive User-Agent that says who is calling.
HEADERS = {"User-Agent": "AITravelAnalysis/1.0 (https://ai-travel-analysis.streamlit.app/; airport photo lookup) python-requests"}
TIMEOUT_SECONDS = 6
GENERIC_WORDS = {
    "airport", "international", "intl", "regional", "municipal", "county", "domestic", "national",
    "airfield", "field", "airstrip", "aerodrome", "civil", "metropolitan", "memorial", "the", "and", "of",
}


def _distinctive_words(text: str) -> set:
    return {w for w in re.findall(r"[^\W\d_]{3,}", text.lower()) if w not in GENERIC_WORDS}


def _safe_image_url(url: Any) -> Optional[str]:
    """Only https images from Wikimedia or Google's thumbnail servers are ever displayed."""
    if not isinstance(url, str):
        return None
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if parsed.scheme == "https" and (host == "upload.wikimedia.org" or host.endswith(".gstatic.com")):
        return url
    return None


def _get_json(url: str, params: Optional[dict] = None) -> Optional[dict]:
    try:
        response = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT_SECONDS)
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, dict) else None
    except requests.exceptions.HTTPError as exc:
        logger.warning("Airport photo: HTTP %s from %s", getattr(exc.response, "status_code", "?"), urlparse(url).hostname)
    except (requests.exceptions.RequestException, ValueError) as exc:
        logger.warning("Airport photo: request to %s failed (%s)", urlparse(url).hostname, redact(type(exc).__name__))
    return None


def _wiki_page(title: str) -> str:
    return "https://en.wikipedia.org/wiki/" + title.replace(" ", "_")


def _from_wikipedia_search(name: str, keywords: set) -> Optional[Dict[str, str]]:
    params = {
        "action": "query", "format": "json", "generator": "search", "gsrsearch": name,
        "gsrlimit": 6, "prop": "pageimages", "piprop": "thumbnail", "pithumbsize": 700, "redirects": 1,
    }
    data = _get_json(WIKI_API, params) or {}
    pages = (data.get("query") or {}).get("pages") or {}
    for page in sorted(pages.values(), key=lambda p: p.get("index", 99)):
        title = str(page.get("title", ""))
        url = _safe_image_url((page.get("thumbnail") or {}).get("source"))
        if url and keywords & _distinctive_words(title) and "airport" in title.lower():
            return {"url": url, "title": title, "page": _wiki_page(title), "credit": "Wikipedia"}
    return None


def _from_wikipedia_summary(name: str, keywords: set) -> Optional[Dict[str, str]]:
    data = _get_json(WIKI_SUMMARY + quote(name.replace(" ", "_"), safe="")) or {}
    title = str(data.get("title", ""))
    image = data.get("thumbnail") or data.get("originalimage") or {}
    url = _safe_image_url(image.get("source"))
    if url and data.get("type") != "disambiguation" and keywords & _distinctive_words(title):
        return {"url": url, "title": title, "page": _wiki_page(title), "credit": "Wikipedia"}
    return None


def _from_google_images(name: str, city: str, keywords: set) -> Optional[Dict[str, str]]:
    try:
        data = serpapi_search({"engine": "google_images", "q": f"{name} {city}".strip(), "hl": "en", "gl": "us"})
    except ProviderError as exc:
        logger.warning("Airport photo: Google Images lookup failed (%s)", redact(exc))
        return None
    for item in data.get("images_results") or []:
        haystack = f"{item.get('title', '')} {item.get('source', '')} {item.get('link', '')}".lower()
        url = _safe_image_url(item.get("thumbnail"))
        if url and any(k in haystack for k in keywords):
            link = item.get("link") if str(item.get("link", "")).startswith("https://") else ""
            return {"url": url, "title": str(item.get("title", name)), "page": link, "credit": "Google Images"}
    return None


def find_airport_photo(code: str) -> Optional[Dict[str, str]]:
    """Return {'url', 'title', 'page', 'credit'} for the airport, or None. Never raises."""
    info = airport_info(code)
    if not info:
        return None
    name = _clean_airport_name(info.get("name", ""))
    city = info.get("city", "") or ""
    if not name:
        return None
    keywords = _distinctive_words(name) or _distinctive_words(city)
    if not keywords:
        return None
    for lookup in (
        lambda: _from_wikipedia_search(name, keywords),
        lambda: _from_wikipedia_summary(name, keywords),
        lambda: _from_google_images(name, city, keywords),
    ):
        try:
            found = lookup()
        except Exception as exc:  # a photo problem must never break the page
            logger.warning("Airport photo lookup error: %s", redact(exc))
            found = None
        if found:
            return found
    logger.info("Airport photo: nothing found for %s", code)
    return None
