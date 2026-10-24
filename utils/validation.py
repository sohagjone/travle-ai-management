"""Input validation for the travel form. Returns friendly messages, never raises."""

from __future__ import annotations

import re
from datetime import date
from functools import lru_cache
from typing import Any, Dict, List, Optional

import airportsdata

_AIRPORTS = airportsdata.load("IATA")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")

MAX_TRAVELLERS = 9  # Google Flights limit for adults + children
MAX_ROOMS = 8


def normalise_airport_code(value: str) -> str:
    return (value or "").strip().upper()


def airport_info(code: str) -> Optional[Dict[str, Any]]:
    """Return airport details (city, name, country) for an IATA code, or None."""
    return _AIRPORTS.get(normalise_airport_code(code))


def city_for_airport(code: str) -> Optional[str]:
    info = airport_info(code)
    return info["city"] if info and info.get("city") else None


def is_valid_email(value: str) -> bool:
    return bool(_EMAIL_RE.match((value or "").strip())) and len(value) <= 254


def validate_travel_request(
    origin: str,
    destination: str,
    departure_date: Optional[date],
    return_date: Optional[date],
    adults: int,
    children: int,
    rooms: int,
    children_ages: Optional[List[int]] = None,
    today: Optional[date] = None,
) -> List[str]:
    """Return a list of human-readable problems (empty list = valid)."""
    errors: List[str] = []
    today = today or date.today()
    origin_code = normalise_airport_code(origin)
    dest_code = normalise_airport_code(destination)

    for label, code in (("Origin", origin_code), ("Destination", dest_code)):
        if not code:
            errors.append(f"{label} airport code is required (e.g. MAD).")
        elif not re.fullmatch(r"[A-Z]{3}", code):
            errors.append(f"{label} must be a 3-letter IATA airport code (e.g. MAD, AMS).")
        elif airport_info(code) is None:
            errors.append(f"{label} code '{code}' was not found in the airport list. Please check it.")

    if origin_code and origin_code == dest_code:
        errors.append("Origin and destination must be different airports.")

    if departure_date is None:
        errors.append("Departure date is required.")
    elif departure_date < today:
        errors.append("Departure date cannot be in the past.")
    if return_date is None:
        errors.append("Return date is required.")
    if departure_date and return_date and return_date <= departure_date:
        errors.append("Return date must be later than the departure date.")

    if not isinstance(adults, int) or adults < 1:
        errors.append("At least 1 adult is required.")
    if not isinstance(children, int) or children < 0:
        errors.append("Number of children cannot be negative.")
    if not isinstance(rooms, int) or rooms < 1:
        errors.append("At least 1 room is required.")
    if isinstance(adults, int) and isinstance(children, int) and adults + children > MAX_TRAVELLERS:
        errors.append(f"Adults + children cannot exceed {MAX_TRAVELLERS} travellers.")
    if isinstance(rooms, int) and rooms > MAX_ROOMS:
        errors.append(f"Rooms cannot exceed {MAX_ROOMS}.")
    if isinstance(rooms, int) and isinstance(adults, int) and adults >= 1 and rooms > adults:
        errors.append("Number of rooms cannot be greater than the number of adults.")

    if isinstance(children, int) and children > 0:
        ages = children_ages or []
        if len(ages) != children:
            errors.append("Please enter an age for each child (needed for hotel pricing).")
        elif any(not isinstance(a, int) or a < 0 or a > 17 for a in ages):
            errors.append("Children's ages must be between 0 and 17.")
    return errors


# ------------------------------------------------------------ airport dropdown
def _clean_airport_name(name: str) -> str:
    """'Dhaka / Hazrat Shahjalal International Airport' -> 'Hazrat Shahjalal International Airport'."""
    name = (name or "").strip()
    return name.split(" / ")[-1].strip() if " / " in name else name


# Friendlier country names than the official ISO ones (e.g. "Korea, Republic of").
_COUNTRY_OVERRIDES = {
    "US": "United States", "GB": "United Kingdom", "KR": "South Korea", "KP": "North Korea",
    "RU": "Russia", "VN": "Vietnam", "IR": "Iran", "SY": "Syria", "TW": "Taiwan", "TZ": "Tanzania",
    "BO": "Bolivia", "VE": "Venezuela", "MD": "Moldova", "LA": "Laos", "PS": "Palestine",
    "FM": "Micronesia", "BN": "Brunei", "CD": "DR Congo", "CG": "Congo", "CI": "Ivory Coast",
    "CV": "Cape Verde", "MK": "North Macedonia", "TR": "Turkey", "HK": "Hong Kong", "MO": "Macau",
}


@lru_cache(maxsize=None)
def country_name(iso_code: str) -> str:
    """'BD' -> 'Bangladesh'. Falls back to the ISO code if the name is unknown."""
    iso_code = (iso_code or "").upper()
    if iso_code in _COUNTRY_OVERRIDES:
        return _COUNTRY_OVERRIDES[iso_code]
    try:
        import pycountry

        country = pycountry.countries.get(alpha_2=iso_code)
        if country:
            return getattr(country, "common_name", None) or country.name
    except Exception:
        pass
    return iso_code


def _label_for(code: str, info: Dict[str, Any]) -> Optional[str]:
    """'DAC-Hazrat Shahjalal International Airport, Bangladesh'."""
    name = _clean_airport_name(info.get("name", ""))
    if not name:
        return None
    country = country_name(info.get("country", ""))
    return f"{code}-{name}, {country}" if country else f"{code}-{name}"


@lru_cache(maxsize=1)
def airport_choices() -> tuple:
    """(labels, label_to_code) for the dropdown. Label pattern: 'DAC-Hazrat Shahjalal International Airport, Bangladesh'."""
    label_to_code = {}
    for code, info in sorted(_AIRPORTS.items()):
        label = _label_for(code, info)
        if label:
            label_to_code[label] = code
    return list(label_to_code.keys()), label_to_code


def airport_label(code: str) -> Optional[str]:
    info = airport_info(code)
    if not info:
        return None
    return _label_for(normalise_airport_code(code), info)


def code_from_label(label: Optional[str]) -> str:
    """Airport code for a dropdown label ('' when nothing is selected)."""
    if not label:
        return ""
    return airport_choices()[1].get(label, "")


def airports_by_city(city: str) -> List[str]:
    """IATA codes of airports whose city matches the text (case-insensitive, exact)."""
    wanted = (city or "").strip().lower()
    if not wanted:
        return []
    return sorted(code for code, info in _AIRPORTS.items() if (info.get("city") or "").lower() == wanted)
