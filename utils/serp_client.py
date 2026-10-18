"""One small, safe wrapper around the SerpAPI REST endpoint.

Used by both the flight and hotel agents so timeouts, error handling and
secret redaction live in a single place.
"""

from __future__ import annotations

from typing import Any, Dict

import requests

from .config import get_secret, logger, redact

SERPAPI_URL = "https://serpapi.com/search.json"
REQUEST_TIMEOUT_SECONDS = 40


class ProviderError(Exception):
    """A search provider problem, with a message that is safe to show to users."""


class NoResultsError(ProviderError):
    """The provider answered correctly but has no results for this search."""


def serpapi_search(params: Dict[str, Any]) -> Dict[str, Any]:
    """Call SerpAPI and return the decoded JSON.

    Raises ProviderError (never leaking the API key) for: missing key, timeouts,
    network problems, invalid key (401/403), rate limits / exhausted quota (429),
    server errors, non-JSON replies and `error` messages inside the JSON.
    """
    api_key = get_secret("SERPAPI_API_KEY")
    if not api_key:
        raise ProviderError(
            "SERPAPI_API_KEY is not configured. Add it to your environment, "
            "a local .env file, or the Streamlit secrets."
        )

    # Drop empty values: sending `sort_by=` or `hotel_class=` can confuse the API.
    clean = {k: v for k, v in params.items() if v not in (None, "")}
    clean["api_key"] = api_key
    engine = clean.get("engine", "search")
    logger.info("SerpAPI request: engine=%s", engine)  # never log the params (api key)

    try:
        response = requests.get(SERPAPI_URL, params=clean, timeout=REQUEST_TIMEOUT_SECONDS)
    except requests.exceptions.Timeout:
        raise ProviderError(f"The {engine} search timed out. Please try again.") from None
    except requests.exceptions.RequestException as exc:
        raise ProviderError(f"Could not reach the search provider: {redact(exc)}") from None

    try:
        payload = response.json()
    except ValueError:
        payload = None

    api_message = ""
    if isinstance(payload, dict) and payload.get("error"):
        api_message = redact(payload["error"])

    if response.status_code in (401, 403):
        raise ProviderError("The SerpAPI key was rejected (invalid or not authorised).")
    if response.status_code == 429:
        raise ProviderError(
            "SerpAPI rate limit or search quota reached. "
            + (api_message or "Try again later or check your SerpAPI plan.")
        )
    if response.status_code >= 500:
        raise ProviderError(f"The search provider had a server error ({response.status_code}).")
    if response.status_code >= 400:
        raise ProviderError(
            f"The search provider rejected the request ({response.status_code}). {api_message}".strip()
        )
    if not isinstance(payload, dict):
        raise ProviderError("The search provider returned an unreadable response.")
    if api_message:
        if "hasn't returned any results" in api_message or "no results" in api_message.lower():
            raise NoResultsError(api_message)
        raise ProviderError(api_message)
    return payload
