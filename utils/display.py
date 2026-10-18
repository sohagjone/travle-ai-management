"""Small helpers for the on-screen results (formatting, sorting, highlights). No Streamlit here."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

FLIGHT_SORTS = {
    "Price (low to high)": lambda f: (f.get("price") is None, f.get("price") or 0),
    "Duration (shortest)": lambda f: (f.get("duration_minutes") is None, f.get("duration_minutes") or 0),
    "Departure (earliest)": lambda f: (not f.get("departure"), f.get("departure") or ""),
}
HOTEL_SORTS = {
    "Rating (highest)": lambda h: (h.get("rating") is None, -(h.get("rating") or 0)),
    "Price per night (low to high)": lambda h: (h.get("price_per_night") is None, h.get("price_per_night") or 0),
    "Most reviews": lambda h: (h.get("reviews") is None, -(h.get("reviews") or 0)),
}


def _parse(value: Optional[str]) -> Optional[datetime]:
    try:
        return datetime.strptime(str(value), "%Y-%m-%d %H:%M")
    except ValueError:
        return None


def fmt_time(value: Optional[str]) -> str:
    dt = _parse(value)
    return dt.strftime("%H:%M") if dt else "n/a"


def fmt_date(value: Optional[str]) -> str:
    dt = _parse(value)
    return f"{dt.strftime('%a')} {dt.day} {dt.strftime('%b')}" if dt else ""


def day_offset(departure: Optional[str], arrival: Optional[str]) -> str:
    """'+1' when the flight lands on a later calendar day."""
    d, a = _parse(departure), _parse(arrival)
    if d and a and a.date() > d.date():
        return f"+{(a.date() - d.date()).days}"
    return ""


def stops_text(stops: Optional[int]) -> str:
    if stops is None:
        return "Stops n/a"
    return "Nonstop" if stops == 0 else f"{stops} stop" + ("s" if stops > 1 else "")


def md_link(url: str, label: str) -> str:
    """Markdown link that survives parentheses/spaces in URLs (Streamlit opens it in a new tab)."""
    return f"[{label}]({url.replace('(', '%28').replace(')', '%29').replace(' ', '%20')})"


def flight_highlights(flights: List[Dict[str, Any]]) -> Dict[str, Optional[Dict[str, Any]]]:
    priced = [f for f in flights if f.get("price") is not None]
    timed = [f for f in flights if f.get("duration_minutes")]
    return {
        "cheapest": min(priced, key=lambda f: f["price"], default=None),
        "fastest": min(timed, key=lambda f: f["duration_minutes"], default=None),
    }


def hotel_highlights(hotels: List[Dict[str, Any]]) -> Dict[str, Optional[Dict[str, Any]]]:
    rated = [h for h in hotels if h.get("rating") is not None]
    priced = [h for h in hotels if h.get("price_per_night") is not None]
    return {
        "top_rated": max(rated, key=lambda h: (h["rating"], h.get("reviews") or 0), default=None),
        "lowest_price": min(priced, key=lambda h: h["price_per_night"], default=None),
    }


# ------------------------------------------------------------------ filters
# A filter that is left at its "everything" setting is skipped, so rows with a
# missing value (no price, no rating...) are not hidden unless you really filter.
def _hour(value: Optional[str]) -> Optional[int]:
    dt = _parse(value)
    return dt.hour if dt else None


def filter_flights(
    rows: List[Dict[str, Any]],
    price_range: Optional[tuple] = None,
    price_bounds: Optional[tuple] = None,
    airlines: Optional[List[str]] = None,
    max_stops: Optional[int] = None,
    max_hours: Optional[float] = None,
    max_hours_bound: Optional[float] = None,
    depart_hours: Optional[tuple] = None,
) -> List[Dict[str, Any]]:
    out = []
    for f in rows:
        if price_range and price_range != price_bounds:
            if f.get("price") is None or not price_range[0] <= f["price"] <= price_range[1]:
                continue
        if airlines:
            if not set(f.get("airlines_list") or []) & set(airlines):
                continue
        if max_stops is not None and (f.get("stops") is None or f["stops"] > max_stops):
            continue
        if max_hours is not None and max_hours != max_hours_bound:
            if not f.get("duration_minutes") or f["duration_minutes"] > max_hours * 60:
                continue
        if depart_hours and depart_hours != (0, 23):
            h = _hour(f.get("departure"))
            if h is None or not depart_hours[0] <= h <= depart_hours[1]:
                continue
        out.append(f)
    return out


def filter_hotels(
    rows: List[Dict[str, Any]],
    price_range: Optional[tuple] = None,
    price_bounds: Optional[tuple] = None,
    min_rating: float = 0.0,
    classes: Optional[List[str]] = None,
    amenities: Optional[List[str]] = None,
    name_query: str = "",
) -> List[Dict[str, Any]]:
    out = []
    query = (name_query or "").strip().lower()
    for h in rows:
        if price_range and price_range != price_bounds:
            p = h.get("price_per_night")
            if p is None or not price_range[0] <= p <= price_range[1]:
                continue
        if min_rating and (h.get("rating") is None or h["rating"] < min_rating):
            continue
        if classes and h.get("hotel_class") not in classes:
            continue
        if amenities and not set(amenities) <= set(h.get("amenities_list") or []):
            continue
        if query and query not in (h.get("name") or "").lower():
            continue
        out.append(h)
    return out


def airline_options(rows: List[Dict[str, Any]]) -> List[str]:
    return sorted({a for f in rows for a in (f.get("airlines_list") or [])})


def amenity_options(rows: List[Dict[str, Any]], limit: int = 25) -> List[str]:
    counts: Dict[str, int] = {}
    for h in rows:
        for a in h.get("amenities_list") or []:
            counts[a] = counts.get(a, 0) + 1
    return [a for a, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]]
