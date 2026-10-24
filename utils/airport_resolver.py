"""Turn what a person (or an AI model) types - "Amsterdam", "AMS", "Dhaka (DAC)" - into one airport.

Uses the offline `airportsdata` list already used by the form, so no API call is needed.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from .validation import _AIRPORTS, normalise_airport_code

# Cities with several airports: pick the one most travellers mean.
PREFERRED_AIRPORT = {
    "london": "LHR", "new york": "JFK", "paris": "CDG", "tokyo": "HND", "moscow": "SVO",
    "milan": "MXP", "rome": "FCO", "chicago": "ORD", "washington": "IAD", "los angeles": "LAX",
    "san francisco": "SFO", "dubai": "DXB", "istanbul": "IST", "bangkok": "BKK", "dhaka": "DAC",
    "kolkata": "CCU", "delhi": "DEL", "new delhi": "DEL", "mumbai": "BOM", "singapore": "SIN",
    "kuala lumpur": "KUL", "ho chi minh city": "SGN", "hanoi": "HAN", "hong kong": "HKG",
    "seoul": "ICN", "beijing": "PEK", "shanghai": "PVG", "sydney": "SYD", "toronto": "YYZ",
    "sao paulo": "GRU", "buenos aires": "EZE", "osaka": "KIX", "berlin": "BER", "madrid": "MAD",
    "amsterdam": "AMS", "barcelona": "BCN", "lisbon": "LIS", "cairo": "CAI", "doha": "DOH",
    "abu dhabi": "AUH", "jeddah": "JED", "riyadh": "RUH", "jessore": "JSR", "chittagong": "CGP",
    "chattogram": "CGP", "colombo": "CMB", "kathmandu": "KTM", "karachi": "KHI", "lahore": "LHE",
}

_CODE_IN_TEXT = re.compile(r"\(([A-Za-z]{3})\)|\b([A-Z]{3})\b")


def _describe(code: str) -> Dict[str, Any]:
    info = _AIRPORTS[code]
    return {"code": code, "city": info.get("city") or "", "name": info.get("name") or "", "country": info.get("country") or ""}


def resolve_airport(text: Optional[str]) -> Optional[Dict[str, Any]]:
    """Best airport for `text`, or None. `alternatives` lists other airports of the same city."""
    raw = (text or "").strip()
    if not raw:
        return None

    # 1) an IATA code, bare or inside text such as "Dhaka (DAC)"
    if re.fullmatch(r"[A-Za-z]{3}", raw) and normalise_airport_code(raw) in _AIRPORTS:
        return {**_describe(normalise_airport_code(raw)), "alternatives": []}
    match = _CODE_IN_TEXT.search(raw)
    if match:
        code = normalise_airport_code(match.group(1) or match.group(2))
        if code in _AIRPORTS:
            return {**_describe(code), "alternatives": []}

    # 2) a city name
    wanted = re.sub(r"\s*\(.*?\)\s*", " ", raw).split(",")[0].strip().lower()
    if not wanted:
        return None
    preferred = PREFERRED_AIRPORT.get(wanted)
    if preferred not in _AIRPORTS:
        preferred = None
    exact = [c for c, i in _AIRPORTS.items() if (i.get("city") or "").lower() == wanted]
    candidates = exact or [c for c, i in _AIRPORTS.items() if wanted in (i.get("city") or "").lower()]
    if not candidates:
        # City not in the list under that spelling (e.g. Jessore / "Jashahor"): try airport names.
        candidates = [c for c, i in _AIRPORTS.items() if wanted in (i.get("name") or "").lower()]
    if preferred:
        best = preferred
    elif candidates:
        best = sorted(candidates, key=lambda c: (0 if "international" in (_AIRPORTS[c].get("name") or "").lower() else 1, c))[0]
    else:
        return None
    city = _AIRPORTS[best].get("city")
    same_city = [c for c, i in _AIRPORTS.items() if i.get("city") == city] if city else candidates
    others: List[str] = [c for c in sorted(set(same_city) | set(candidates)) if c != best][:4]
    return {**_describe(best), "alternatives": [_describe(c) for c in others]}
