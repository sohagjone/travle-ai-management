"""Turns raw search results into ONE clean "report" dictionary.

Every export format (PDF, Excel, CSV, JSON, Word) is generated from the dict
returned by `build_report()`, so they always agree with each other and with
what is shown on screen. Nothing here calls an API; missing data stays missing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from .config import DEFAULT_CURRENCY

SCHEMA_VERSION = "1.0"
CURRENCY_SYMBOLS = {"USD": "$", "EUR": "€", "GBP": "£", "INR": "₹", "JPY": "¥"}
STOPS_LABELS = {
    0: "Any number of stops",
    1: "Nonstop only",
    2: "1 stop or fewer",
    3: "2 stops or fewer",
}


@dataclass(frozen=True)
class Column:
    key: str
    header: str
    kind: str = "text"  # text | money | int | float | url
    width: int = 16


FLIGHT_COLUMNS = [
    Column("option", "Option", "int", 8),
    Column("airline", "Airline", "text", 22),
    Column("flight_number", "Flight number(s)", "text", 18),
    Column("departure_airport", "From", "text", 8),
    Column("departure", "Departure", "text", 18),
    Column("arrival_airport", "To", "text", 8),
    Column("arrival", "Arrival", "text", 18),
    Column("duration", "Duration", "text", 11),
    Column("stops", "Stops", "int", 8),
    Column("price", "Price", "money", 12),
    Column("currency", "Currency", "text", 10),
    Column("booking_url", "Booking link (Google Flights search)", "url", 34),
    Column("top_pick", "Google top pick", "text", 14),
]

HOTEL_COLUMNS = [
    Column("option", "Option", "int", 8),
    Column("name", "Hotel", "text", 32),
    Column("hotel_class", "Class", "text", 16),
    Column("rating", "Rating", "float", 9),
    Column("reviews", "Reviews", "int", 10),
    Column("price_per_night", "Price per night", "money", 15),
    Column("total_price", "Total price", "money", 13),
    Column("currency", "Currency", "text", 10),
    Column("amenities", "Amenities", "text", 40),
    Column("description", "Description", "text", 40),
    Column("booking_url", "Booking / website link", "url", 34),
]


# ----------------------------------------------------------------- helpers
def safe_http_url(url: Any) -> Optional[str]:
    """Return the URL only if it is a plain http(s) link (blocks javascript:, etc.)."""
    if not isinstance(url, str):
        return None
    url = url.strip()
    if not re.match(r"^https?://[^\s<>\"']+$", url, re.IGNORECASE) or len(url) > 2000:
        return None
    return url


def currency_symbol(currency: str) -> str:
    return CURRENCY_SYMBOLS.get((currency or "").upper(), "")


def fmt_money(value: Optional[float], currency: str = DEFAULT_CURRENCY) -> str:
    """'$1,234' (or 'CHF 1,234' when we have no symbol). Missing -> 'n/a'."""
    if value is None:
        return "n/a"
    symbol = currency_symbol(currency)
    number = f"{value:,.0f}" if float(value).is_integer() else f"{value:,.2f}"
    return f"{symbol}{number}" if symbol else f"{currency} {number}"


def display_value(row: Dict[str, Any], column: Column) -> str:
    """Human-readable text for a cell (PDF/Word/screen). Missing -> 'n/a'."""
    value = row.get(column.key)
    if value in (None, "", []):
        return "n/a"
    if column.kind == "money":
        return fmt_money(value, row.get("currency") or DEFAULT_CURRENCY)
    if column.kind == "float":
        return f"{value:.1f}"
    return str(value)


def nights_between(departure: str, return_: str) -> Optional[int]:
    try:
        d1 = date.fromisoformat(str(departure))
        d2 = date.fromisoformat(str(return_))
    except ValueError:
        return None
    return (d2 - d1).days if d2 > d1 else None


def file_stem(report: Dict[str, Any]) -> str:
    """e.g. travel_report_MAD_to_AMS_2026-10-17 (letters/digits only: safe filename)."""
    req = report["request"]
    origin = re.sub(r"[^A-Za-z0-9]", "", req.get("origin", "")) or "XXX"
    dest = re.sub(r"[^A-Za-z0-9]", "", req.get("destination", "")) or "XXX"
    return f"travel_report_{origin}_to_{dest}_{report['generated_date']}"


# ------------------------------------------------------------ normalising
def _flight_rows(flights_result: Optional[Dict[str, Any]], currency: str) -> List[Dict[str, Any]]:
    rows = []
    for i, f in enumerate((flights_result or {}).get("recommended_flights") or [], start=1):
        rows.append(
            {
                "option": i,
                "airline": f.get("airline"),
                "airlines_list": f.get("airlines") or ([f["airline"]] if f.get("airline") else []),
                "flight_number": f.get("flight_number"),
                "departure_airport": f.get("departure_airport"),
                "departure": f.get("departure"),
                "arrival_airport": f.get("arrival_airport"),
                "arrival": f.get("arrival"),
                "duration": f.get("duration"),
                "duration_minutes": f.get("duration_minutes"),
                "stops": f.get("stops"),
                "price": f.get("price_value"),
                "currency": f.get("currency") or currency,
                "booking_url": safe_http_url(f.get("booking_url")),
                "top_pick": "Yes" if f.get("is_top_pick") else "",
                "logo_url": safe_http_url(f.get("logo_url")),
            }
        )
    return rows


def _hotel_rows(hotels_result: Optional[Dict[str, Any]], currency: str) -> List[Dict[str, Any]]:
    rows = []
    for i, h in enumerate((hotels_result or {}).get("recommended_hotels") or [], start=1):
        amenities = h.get("amenities") if isinstance(h.get("amenities"), list) else []
        rows.append(
            {
                "option": i,
                "name": h.get("name"),
                "hotel_class": h.get("hotel_class"),
                "rating": h.get("rating"),
                "reviews": h.get("reviews") if isinstance(h.get("reviews"), int) else None,
                "price_per_night": h.get("price_per_night_value"),
                "total_price": h.get("total_price_value"),
                "currency": h.get("currency") or currency,
                "amenities": "; ".join(str(a) for a in amenities),
                "amenities_list": [str(a) for a in amenities],
                "description": h.get("description"),
                "booking_url": safe_http_url(h.get("booking_url")),
                "image_url": safe_http_url(h.get("image_url")),
            }
        )
    return rows


def estimate_cost(
    flight: Optional[Dict[str, Any]],
    hotel: Optional[Dict[str, Any]],
    nights: Optional[int],
    currency: str,
    label: str,
) -> Dict[str, Any]:
    """Add up only prices that really exist. Never fills a gap with a guess."""
    items: List[Dict[str, Any]] = []
    total = 0.0
    if flight and flight.get("price") is not None:
        items.append(
            {
                "label": f"Flight: {flight.get('airline') or 'option ' + str(flight['option'])} (option {flight['option']})",
                "amount": flight["price"],
                "basis": "Price as returned by Google Flights for this search",
            }
        )
        total += flight["price"]
    if hotel:
        amount, basis = None, ""
        if hotel.get("total_price") is not None:
            amount, basis = hotel["total_price"], "Total stay price as returned by Google Hotels"
        elif hotel.get("price_per_night") is not None and nights:
            amount = hotel["price_per_night"] * nights
            basis = f"Calculated: nightly rate x {nights} nights (provider gave no total)"
        if amount is not None:
            items.append({"label": f"Hotel: {hotel.get('name')} (option {hotel['option']})", "amount": amount, "basis": basis})
            total += amount
    kinds = {"Flight" if i["label"].startswith("Flight") else "Hotel" for i in items}
    return {
        "scenario": label,
        "items": items,
        "total": total if items else None,
        "currency": currency,
        "complete": kinds == {"Flight", "Hotel"},
    }


EXCLUDED_FROM_ESTIMATE = [
    "Checked baggage, seat selection and other airline fees (unless already in the fare)",
    "Airport transfers and local transport",
    "Meals, activities and spending money",
    "Travel insurance, visas and vaccinations",
    "Hotel taxes, resort or city fees not included in the provider's price",
    "Currency conversion or card fees",
]


def build_report(
    request: Dict[str, Any],
    flights_result: Optional[Dict[str, Any]],
    hotels_result: Optional[Dict[str, Any]],
    recommendations: Optional[Dict[str, Any]] = None,
    errors: Optional[List[str]] = None,
    generated_at: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Create the single report dict that every exporter uses."""
    now = generated_at or datetime.now(timezone.utc)
    currency = request.get("currency") or DEFAULT_CURRENCY
    flights = _flight_rows(flights_result, currency)
    hotels = _hotel_rows(hotels_result, currency)
    nights = nights_between(request.get("departure_date", ""), request.get("return_date", ""))

    # Public copy of the request: the email address is deliberately NOT included.
    public_request = {
        "origin": request.get("origin"),
        "destination": request.get("destination"),
        "origin_city": request.get("origin_city"),
        "destination_city": request.get("destination_city"),
        "hotel_search_city": (hotels_result or {}).get("search_city") or request.get("city"),
        "departure_date": request.get("departure_date"),
        "return_date": request.get("return_date"),
        "nights": nights,
        "adults": request.get("adults"),
        "children": request.get("children"),
        "children_ages": request.get("children_ages") or [],
        "rooms": request.get("rooms"),
        "flight_stops_filter": STOPS_LABELS.get(request.get("stops", 1), "Unknown"),
        "currency": currency,
    }

    recs = recommendations or {"source": "none", "source_label": "No recommendations available", "summary": None}
    by_option_f = {f["option"]: f for f in flights}
    by_option_h = {h["option"]: h for h in hotels}
    rec_f = by_option_f.get((recs.get("best_flight") or {}).get("option"))
    rec_h = by_option_h.get((recs.get("best_hotel") or {}).get("option"))
    cheapest_f = min((f for f in flights if f["price"] is not None), key=lambda f: f["price"], default=None)
    priced_h = [h for h in hotels if h["total_price"] is not None or (h["price_per_night"] is not None and nights)]
    cheapest_h = min(
        priced_h,
        key=lambda h: h["total_price"] if h["total_price"] is not None else h["price_per_night"] * nights,
        default=None,
    )
    scenarios = [estimate_cost(cheapest_f, cheapest_h, nights, currency, "Lowest-priced flight + lowest-priced hotel")]
    if (rec_f or rec_h) and (
        (rec_f and rec_f is not cheapest_f) or (rec_h and rec_h is not cheapest_h)
    ):
        scenarios.append(
            estimate_cost(rec_f or cheapest_f, rec_h or cheapest_h, nights, currency, "Recommended flight + recommended hotel")
        )
    scenarios = [s for s in scenarios if s["items"]]

    sources = []
    if flights_result:
        sources.append({"name": flights_result.get("source", "Flights provider"), "type": "Flights", "retrieved": flights_result.get("search_timestamp"), "link": safe_http_url(flights_result.get("search_url"))})
    if hotels_result:
        sources.append({"name": hotels_result.get("source", "Hotels provider"), "type": "Hotels", "retrieved": hotels_result.get("search_timestamp"), "link": None})
    ai_label = recs.get("source_label")
    if ai_label:
        sources.append({"name": ai_label, "type": "Recommendations", "retrieved": None, "link": None})

    notes = [
        "Prices and availability are search results, not bookings. They can change at any time; verify the final price and conditions on the booking page.",
        "Flight prices are shown exactly as returned by the provider for the submitted search (currency: " + currency + "). Please confirm on the booking page whether a price is per passenger or for the whole party.",
        "The flight 'booking link' is a Google Flights search link for this whole search, not a link to one specific fare.",
        "Hotel links are the website/listing link returned by the provider and may not be a direct booking page.",
        "Fields that the provider did not return are shown as 'n/a' or left blank; nothing has been estimated or invented, except where a line says 'Calculated'.",
    ]
    if recs.get("source") == "rule_based":
        notes.append("No AI model was used: recommendations are simple rules applied to the returned data (lowest flight price, best-rated hotel).")
    if not flights:
        notes.append("No flight options were returned for this search.")
    if not hotels:
        notes.append("No hotel options were returned for this search.")
    for message in errors or []:
        notes.append("Problem during search: " + message)

    return {
        "schema_version": SCHEMA_VERSION,
        "title": "Travel Search Report",
        "generated_at": now.isoformat(timespec="seconds"),
        "generated_at_display": now.strftime("%Y-%m-%d %H:%M UTC"),
        "generated_date": now.strftime("%Y-%m-%d"),
        "request": public_request,
        "flights": flights,
        "hotels": hotels,
        "recommendations": recs,
        "cost_estimate": {"scenarios": scenarios, "excluded": EXCLUDED_FROM_ESTIMATE},
        "sources": sources,
        "notes": notes,
        "errors": list(errors or []),
    }


_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def clean_text(value: Any) -> str:
    """Text that is safe to put in any file: no control characters (they corrupt XML-based files)."""
    return _CONTROL_CHARS.sub("", "" if value is None else str(value))
