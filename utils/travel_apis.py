"""Data providers for the AI travel agent: weather, currency, attractions, web search.

* Weather  - Open-Meteo (free, no API key). Forecast for the next ~2 weeks; for later dates
             the SAME dates last year are shown and clearly labelled as "typical", not a forecast.
* Currency - open.er-api.com (free, no key), with Frankfurter (ECB) as a backup.
* Attractions and web search - SerpAPI (the key the app already uses).

Every function raises ProviderError with a message that is safe to show to people.
"""

from __future__ import annotations

import re
import threading
import time
from datetime import date, timedelta
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlparse

import requests

from .config import logger, redact
from .serp_client import NoResultsError, ProviderError, serpapi_search

HTTP_TIMEOUT_SECONDS = 20
FORECAST_HORIZON_DAYS = 15  # Open-Meteo forecasts reach about 16 days (today + 15)

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
RATES_URL = "https://open.er-api.com/v6/latest/{base}"
FRANKFURTER_URL = "https://api.frankfurter.dev/v1/latest"

# WMO weather codes used by Open-Meteo.
WEATHER_CODES = {
    0: "Clear sky", 1: "Mostly clear", 2: "Partly cloudy", 3: "Overcast", 45: "Fog", 48: "Rime fog",
    51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle", 56: "Freezing drizzle", 57: "Heavy freezing drizzle",
    61: "Light rain", 63: "Rain", 65: "Heavy rain", 66: "Freezing rain", 67: "Heavy freezing rain",
    71: "Light snow", 73: "Snow", 75: "Heavy snow", 77: "Snow grains", 80: "Light showers", 81: "Showers",
    82: "Violent showers", 85: "Snow showers", 86: "Heavy snow showers", 95: "Thunderstorm",
    96: "Thunderstorm with hail", 99: "Severe thunderstorm with hail",
}

_cache: Dict[str, tuple] = {}
_cache_lock = threading.Lock()


def _cached(key: str, ttl_seconds: int, compute: Callable[[], Any]) -> Any:
    now = time.time()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and hit[0] > now:
            return hit[1]
    value = compute()  # a failure is never cached
    with _cache_lock:
        _cache[key] = (now + ttl_seconds, value)
    return value


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


def _get_json(url: str, params: Optional[Dict[str, Any]] = None) -> Any:
    host = urlparse(url).netloc
    try:
        response = requests.get(url, params=params, timeout=HTTP_TIMEOUT_SECONDS)
    except requests.exceptions.Timeout:
        raise ProviderError(f"{host} timed out. Please try again.") from None
    except requests.exceptions.RequestException as exc:
        raise ProviderError(f"Could not reach {host}: {redact(exc)}") from None
    if response.status_code == 429:
        raise ProviderError(f"{host} is rate-limiting requests right now. Try again in a minute.")
    if response.status_code >= 400:
        raise ProviderError(f"{host} returned an error ({response.status_code}).")
    try:
        return response.json()
    except ValueError:
        raise ProviderError(f"{host} returned an unreadable response.") from None


# ------------------------------------------------------------------ weather
def geocode(place: str) -> Dict[str, Any]:
    place = (place or "").strip()
    if not place:
        raise ProviderError("No place name was given.")

    def compute() -> Dict[str, Any]:
        data = _get_json(GEOCODE_URL, {"name": place, "count": 1, "language": "en", "format": "json"})
        results = (data or {}).get("results") if isinstance(data, dict) else None
        if not results:
            raise ProviderError(f"Could not find a place called '{place}'.")
        r = results[0]
        return {"name": r.get("name") or place, "country": r.get("country") or "", "latitude": r["latitude"], "longitude": r["longitude"]}

    return _cached(f"geo:{place.lower()}", 7 * 24 * 3600, compute)


def _same_dates_last_year(start: date, end: date) -> tuple:
    def shift(d: date) -> date:
        try:
            return d.replace(year=d.year - 1)
        except ValueError:  # 29 Feb
            return d.replace(year=d.year - 1, day=28)
    return shift(start), shift(end)


def _daily_rows(daily: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = []
    for i, day in enumerate(daily.get("time") or []):
        def at(key: str) -> Optional[float]:
            values = daily.get(key) or []
            return values[i] if i < len(values) and isinstance(values[i], (int, float)) else None
        code = at("weather_code") if "weather_code" in daily else at("weathercode")  # Open-Meteo renamed this field
        rows.append({
            "date": day,
            "condition": WEATHER_CODES.get(int(code), "Unknown") if code is not None else "Unknown",
            "temp_max_c": at("temperature_2m_max"),
            "temp_min_c": at("temperature_2m_min"),
            "rain_mm": at("precipitation_sum"),
            "rain_chance_pct": at("precipitation_probability_max"),
        })
    return rows


def get_weather(city: str, start: date, end: date, today: Optional[date] = None) -> Dict[str, Any]:
    """Weather for a trip. `mode` says whether it is a real forecast or a typical-weather estimate."""
    today = today or date.today()
    if end < start:
        raise ProviderError("The end date is before the start date.")
    place = geocode(city)
    base = {"latitude": place["latitude"], "longitude": place["longitude"], "timezone": "auto"}
    fields = "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum"

    if end < today:
        mode, url = "observed", ARCHIVE_URL
        params = {**base, "daily": fields, "start_date": start.isoformat(), "end_date": end.isoformat()}
        note = "Observed weather on those dates."
    elif start >= today and end <= today + timedelta(days=FORECAST_HORIZON_DAYS):
        mode, url = "forecast", FORECAST_URL
        params = {**base, "daily": fields + ",precipitation_probability_max", "start_date": start.isoformat(), "end_date": end.isoformat()}
        note = "Real forecast. Forecasts change - check again closer to departure."
    else:
        s, e = _same_dates_last_year(start, end)
        mode, url = "typical_from_last_year", ARCHIVE_URL
        params = {**base, "daily": fields, "start_date": s.isoformat(), "end_date": e.isoformat()}
        note = (
            "These dates are too far ahead for a forecast. Showing what the weather was on the SAME dates last year "
            "as a guide to typical conditions - it is NOT a forecast for your trip."
        )

    data = _cached(f"wx:{url}:{sorted(params.items())}", 3 * 3600, lambda: _get_json(url, params))
    daily = data.get("daily") if isinstance(data, dict) else None
    rows = _daily_rows(daily if isinstance(daily, dict) else {})
    if not rows:
        raise ProviderError(f"No weather data was returned for {place['name']} on those dates.")
    if mode == "typical_from_last_year":  # show the trip's own dates next to last year's values
        offset = start - date.fromisoformat(rows[0]["date"])
        for row in rows:
            row["reference_date"] = row["date"]
            row["date"] = (date.fromisoformat(row["date"]) + offset).isoformat()

    highs = [r["temp_max_c"] for r in rows if r["temp_max_c"] is not None]
    lows = [r["temp_min_c"] for r in rows if r["temp_min_c"] is not None]
    rain = [r["rain_mm"] for r in rows if r["rain_mm"] is not None]
    return {
        "city": place["name"], "country": place["country"], "mode": mode, "note": note,
        "units": {"temperature": "°C", "rain": "mm"},
        "summary": {
            "days": len(rows),
            "avg_high_c": round(sum(highs) / len(highs), 1) if highs else None,
            "avg_low_c": round(sum(lows) / len(lows), 1) if lows else None,
            "rainy_days": sum(1 for r in rain if r >= 1.0),
            "total_rain_mm": round(sum(rain), 1) if rain else None,
        },
        "daily": rows,
        "source": "Open-Meteo",
    }


# ----------------------------------------------------------------- currency
def _rates_for(base: str) -> Dict[str, Any]:
    def compute() -> Dict[str, Any]:
        try:
            data = _get_json(RATES_URL.format(base=base))
            if isinstance(data, dict) and data.get("result") == "success" and isinstance(data.get("rates"), dict):
                return {"rates": data["rates"], "as_of": data.get("time_last_update_utc") or "", "source": "open.er-api.com (Exchange Rate API)"}
            raise ProviderError("The exchange-rate service did not return rates.")
        except ProviderError as first_error:
            logger.info("Primary rates failed (%s); trying Frankfurter", redact(first_error))
            data = _get_json(FRANKFURTER_URL, {"base": base})
            if isinstance(data, dict) and isinstance(data.get("rates"), dict):
                return {"rates": {**data["rates"], base: 1.0}, "as_of": data.get("date") or "", "source": "Frankfurter (European Central Bank)"}
            raise ProviderError("Could not get exchange rates from any provider.") from None

    return _cached(f"fx:{base}", 3600, compute)


def convert_currency(amount: float, from_currency: str, to_currency: str) -> Dict[str, Any]:
    src, dst = (from_currency or "").strip().upper(), (to_currency or "").strip().upper()
    for code in (src, dst):
        if not re.fullmatch(r"[A-Z]{3}", code):
            raise ProviderError(f"'{code or '(empty)'}' is not a 3-letter currency code such as USD or EUR.")
    try:
        value = float(amount)
    except (TypeError, ValueError):
        raise ProviderError("The amount must be a number.") from None
    if src == dst:
        return {"amount": value, "from": src, "to": dst, "rate": 1.0, "converted": round(value, 2), "as_of": "", "source": "same currency"}
    data = _rates_for(src)
    rate = data["rates"].get(dst)
    if not isinstance(rate, (int, float)) or rate <= 0:
        raise ProviderError(f"No exchange rate is available for {src} to {dst}.")
    return {
        "amount": value, "from": src, "to": dst, "rate": float(rate), "converted": round(value * rate, 2),
        "as_of": data["as_of"], "source": data["source"],
        "note": "Mid-market rate. Banks and cards add their own margin or fees.",
    }


# -------------------------------------------------------------- attractions
def find_attractions(city: str, category: str = "", limit: int = 10) -> Dict[str, Any]:
    """Top places to visit in a city (SerpAPI Google Maps)."""
    city = (city or "").strip()
    if not city:
        raise ProviderError("No city was given.")
    query = f"{category.strip()} in {city}" if category and category.strip() else f"top tourist attractions in {city}"
    params: Dict[str, Any] = {"engine": "google_maps", "type": "search", "q": query, "hl": "en"}
    try:  # location bias keeps results inside the right city
        place = geocode(city)
        params["ll"] = f"@{place['latitude']},{place['longitude']},12z"
    except ProviderError:
        pass
    try:
        data = serpapi_search(params)
    except NoResultsError:
        data = {}
    places = []
    for r in (data.get("local_results") or []) if isinstance(data, dict) else []:
        if not isinstance(r, dict) or not r.get("title"):
            continue
        rating = r.get("rating")
        places.append({
            "name": r["title"],
            "type": r.get("type") or (r.get("types") or [None])[0],
            "rating": float(rating) if isinstance(rating, (int, float)) else None,
            "reviews": r.get("reviews") if isinstance(r.get("reviews"), int) else None,
            "address": r.get("address"),
            "description": r.get("description"),
            "thumbnail": r.get("thumbnail"),
            "website": r.get("website"),
        })
    # Best first: rating, then number of reviews.
    places.sort(key=lambda p: (p["rating"] is None, -(p["rating"] or 0), -(p["reviews"] or 0)))
    return {"city": city, "query": query, "places": places[: max(1, min(int(limit), 20))], "source": "SerpAPI - Google Maps"}


# --------------------------------------------------------------- web search
def web_search(query: str, num_results: int = 5) -> Dict[str, Any]:
    query = (query or "").strip()
    if not query:
        raise ProviderError("The search query is empty.")
    num = max(1, min(int(num_results or 5), 10))
    try:
        data = serpapi_search({"engine": "google", "q": query, "num": num, "hl": "en", "gl": "us"})
    except NoResultsError:
        data = {}
    data = data if isinstance(data, dict) else {}
    results = [
        {"title": r.get("title"), "link": r.get("link"), "snippet": r.get("snippet"), "source": r.get("source") or r.get("displayed_link")}
        for r in (data.get("organic_results") or [])[:num] if isinstance(r, dict) and r.get("link")
    ]
    box = data.get("answer_box") if isinstance(data.get("answer_box"), dict) else {}
    quick = box.get("answer") or box.get("snippet") or box.get("result")
    return {"query": query, "quick_answer": str(quick) if quick else None, "results": results, "source": "SerpAPI - Google Search"}
