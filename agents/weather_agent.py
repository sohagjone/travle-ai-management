from typing import Any, Dict, List, Optional
from datetime import date, datetime, timedelta

import requests

from .base_agent import BaseAgent
from utils.config import logger, redact
from utils.serp_client import ProviderError

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_HORIZON_DAYS = 15  # Open-Meteo forecasts reach about 16 days ahead
TYPICAL_YEARS = 3
TIMEOUT = 15
DAILY = "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum"

# WMO weather codes -> (emoji, text)
WMO = {
    0: ("☀️", "Clear sky"), 1: ("🌤️", "Mainly clear"), 2: ("⛅", "Partly cloudy"), 3: ("☁️", "Overcast"),
    45: ("🌫️", "Fog"), 48: ("🌫️", "Freezing fog"),
    51: ("🌦️", "Light drizzle"), 53: ("🌦️", "Drizzle"), 55: ("🌦️", "Heavy drizzle"),
    56: ("🌦️", "Freezing drizzle"), 57: ("🌦️", "Freezing drizzle"),
    61: ("🌧️", "Light rain"), 63: ("🌧️", "Rain"), 65: ("🌧️", "Heavy rain"),
    66: ("🌧️", "Freezing rain"), 67: ("🌧️", "Freezing rain"),
    71: ("🌨️", "Light snow"), 73: ("🌨️", "Snow"), 75: ("🌨️", "Heavy snow"), 77: ("🌨️", "Snow grains"),
    80: ("🌦️", "Rain showers"), 81: ("🌦️", "Rain showers"), 82: ("⛈️", "Violent showers"),
    85: ("🌨️", "Snow showers"), 86: ("🌨️", "Snow showers"),
    95: ("⛈️", "Thunderstorm"), 96: ("⛈️", "Thunderstorm, hail"), 99: ("⛈️", "Thunderstorm, hail"),
}


def describe_code(code: Any) -> tuple:
    return WMO.get(int(code), ("🌡️", "Unknown")) if isinstance(code, (int, float)) and not isinstance(code, bool) else ("🌡️", "n/a")


def _avg(values: List[Optional[float]]) -> Optional[float]:
    nums = [v for v in values if isinstance(v, (int, float))]
    return sum(nums) / len(nums) if nums else None


def _same_day_in_year(d: date, year: int) -> date:
    try:
        return d.replace(year=year)
    except ValueError:  # 29 Feb in a non-leap year
        return d.replace(year=year, day=28)


def _get(url: str, params: Dict[str, Any]) -> Dict[str, Any]:
    try:
        response = requests.get(url, params=params, timeout=TIMEOUT)
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.Timeout:
        raise ProviderError("The weather service timed out.") from None
    except (requests.exceptions.RequestException, ValueError) as exc:
        raise ProviderError(f"The weather service could not be reached ({redact(type(exc).__name__)}).") from None
    if not isinstance(data, dict) or data.get("error"):
        raise ProviderError("The weather service returned an error.")
    return data


def _daily_rows(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    d = data.get("daily") or {}
    times = d.get("time") or []

    def col(name):
        values = d.get(name) or []
        return values + [None] * (len(times) - len(values))

    return [
        {"date": t, "code": c, "tmax": hi, "tmin": lo, "precip": p}
        for t, c, hi, lo, p in zip(times, col("weather_code"), col("temperature_2m_max"), col("temperature_2m_min"), col("precipitation_sum"))
    ]


class WeatherAgent(BaseAgent):
    """Weather for each trip day (Open-Meteo, free, no API key).

    Days within about 15 days from today use the real forecast. Later days show
    TYPICAL weather: the average of the same dates in the last three years.
    """

    def __init__(self):
        super().__init__(name="WeatherAgent", instructions="Provide weather for the trip dates.")

    async def run(self, messages: list) -> Dict[str, Any]:
        return self.get_weather(self._load_payload(messages))

    def get_weather(self, params: Dict[str, Any], today: Optional[date] = None) -> Dict[str, Any]:
        today = today or date.today()
        lat, lon = params.get("lat"), params.get("lon")
        if lat is None or lon is None:
            raise ProviderError("Weather needs the destination's coordinates, which are unknown for this airport.")
        start, end = date.fromisoformat(params["start_date"]), date.fromisoformat(params["end_date"])
        days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
        horizon = today + timedelta(days=FORECAST_HORIZON_DAYS)
        forecast_days = [d for d in days if d <= horizon and d >= today]
        typical_days = [d for d in days if d not in forecast_days]

        rows: List[Dict[str, Any]] = []
        if forecast_days:
            data = _get(FORECAST_URL, {
                "latitude": lat, "longitude": lon, "daily": DAILY, "timezone": "auto",
                "start_date": forecast_days[0].isoformat(), "end_date": forecast_days[-1].isoformat(),
            })
            for r in _daily_rows(data):
                emoji, text = describe_code(r["code"])
                rows.append({**r, "mode": "forecast", "icon": emoji, "summary": text, "rain_chance": None})
        if typical_days:
            rows.extend(self._typical(lat, lon, typical_days, today))
        rows.sort(key=lambda r: r["date"])
        return {
            "days": rows,
            "unit": "°C",
            "has_typical": any(r["mode"] == "typical" for r in rows),
            "has_forecast": any(r["mode"] == "forecast" for r in rows),
            "source": "Open-Meteo (open-meteo.com), CC BY 4.0",
            "search_timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }

    def _typical(self, lat, lon, days: List[date], today: date) -> List[Dict[str, Any]]:
        per_year: List[Dict[str, Dict[str, Any]]] = []
        first, last = days[0], days[-1]
        for back in range(1, TYPICAL_YEARS + 1):
            year = today.year - back
            s = _same_day_in_year(first, year)
            e = _same_day_in_year(last, year + (last.year - first.year))
            try:
                data = _get(ARCHIVE_URL, {
                    "latitude": lat, "longitude": lon, "daily": DAILY, "timezone": "auto",
                    "start_date": s.isoformat(), "end_date": e.isoformat(),
                })
            except ProviderError as exc:
                logger.warning("Typical weather for %s failed: %s", year, exc)
                continue
            # key by offset from the first day so years line up even across leap days
            by_offset = {}
            for r in _daily_rows(data):
                by_offset[(date.fromisoformat(r["date"]) - s).days] = r
            per_year.append(by_offset)
        if not per_year:
            raise ProviderError("Typical weather data could not be loaded.")
        out = []
        for d in days:
            off = (d - first).days
            samples = [y[off] for y in per_year if off in y]
            if not samples:
                continue
            precip = [s["precip"] for s in samples]
            known = [p for p in precip if isinstance(p, (int, float))]
            chance = round(100 * sum(1 for p in known if p >= 1.0) / len(known)) if known else None
            if chance is None:
                icon, text = "🌡️", "Typical conditions"
            elif chance >= 60:
                icon, text = "🌧️", "Often rainy"
            elif chance >= 30:
                icon, text = "⛅", "Some rain possible"
            else:
                icon, text = "☀️", "Mostly dry"
            out.append({
                "date": d.isoformat(), "code": None, "mode": "typical", "icon": icon, "summary": text,
                "tmax": _avg([s["tmax"] for s in samples]), "tmin": _avg([s["tmin"] for s in samples]),
                "precip": _avg(precip), "rain_chance": chance, "years_used": len(samples),
            })
        return out
