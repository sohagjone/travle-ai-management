"""Trip budget = real search prices + the user's OWN estimates (clearly labelled).

Nothing here guesses a price. Flight and hotel amounts come from the search
results; food, local transport, activities and extras are only added when the
user types them in.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional

from .report_data import fmt_money


@dataclass
class Assumptions:
    flight_option: Optional[int] = None      # None = cheapest priced flight
    hotel_option: Optional[int] = None       # None = cheapest priced hotel
    food_per_person_per_day: float = 0.0
    transport_per_day: float = 0.0           # for the whole group
    activities_total: float = 0.0
    other_total: float = 0.0
    convert_to: Optional[str] = None         # e.g. "BDT"

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @property
    def has_extras(self) -> bool:
        return any((self.food_per_person_per_day, self.transport_per_day, self.activities_total, self.other_total))


def _pick(rows: List[Dict[str, Any]], option: Optional[int], price_of) -> Optional[Dict[str, Any]]:
    if option is not None:
        return next((r for r in rows if r["option"] == option), None)
    priced = [r for r in rows if price_of(r) is not None]
    return min(priced, key=price_of, default=None)


def compute_trip_cost(
    report: Dict[str, Any],
    assumptions: Assumptions,
    rates: Optional[Dict[str, Any]] = None,
    convert_fn=None,
) -> Dict[str, Any]:
    req = report["request"]
    currency = req.get("currency") or "USD"
    nights = req.get("nights")
    travellers = (req.get("adults") or 0) + (req.get("children") or 0)
    days = (nights + 1) if nights else None

    def hotel_total(h):
        if h.get("total_price") is not None:
            return h["total_price"]
        if h.get("price_per_night") is not None and nights:
            return h["price_per_night"] * nights
        return None

    flight = _pick(report["flights"], assumptions.flight_option, lambda f: f.get("price"))
    hotel = _pick(report["hotels"], assumptions.hotel_option, hotel_total)

    items: List[Dict[str, Any]] = []
    if flight and flight.get("price") is not None:
        items.append({"category": "Flights", "label": f"{flight.get('airline') or 'Flight'} (option {flight['option']})",
                      "amount": flight["price"], "basis": "Search result (check per-passenger vs whole party on the booking page)", "origin": "search"})
    if hotel and hotel_total(hotel) is not None:
        basis = "Search result: total stay" if hotel.get("total_price") is not None else f"Calculated: nightly rate x {nights} nights"
        items.append({"category": "Hotel", "label": f"{hotel.get('name')} (option {hotel['option']})",
                      "amount": hotel_total(hotel), "basis": basis, "origin": "search"})
    if assumptions.food_per_person_per_day and travellers and days:
        items.append({"category": "Food", "label": f"{fmt_money(assumptions.food_per_person_per_day, currency)} x {travellers} traveller(s) x {days} day(s)",
                      "amount": assumptions.food_per_person_per_day * travellers * days, "basis": "Your estimate", "origin": "you"})
    if assumptions.transport_per_day and days:
        items.append({"category": "Local transport", "label": f"{fmt_money(assumptions.transport_per_day, currency)} x {days} day(s)",
                      "amount": assumptions.transport_per_day * days, "basis": "Your estimate", "origin": "you"})
    if assumptions.activities_total:
        items.append({"category": "Activities", "label": "Tickets and tours", "amount": assumptions.activities_total, "basis": "Your estimate", "origin": "you"})
    if assumptions.other_total:
        items.append({"category": "Other", "label": "Other costs", "amount": assumptions.other_total, "basis": "Your estimate", "origin": "you"})

    total = sum(i["amount"] for i in items) if items else None
    has_flight = any(i["category"] == "Flights" for i in items)
    has_hotel = any(i["category"] == "Hotel" for i in items)
    result: Dict[str, Any] = {
        "currency": currency, "items": items, "total": total,
        "per_person": (total / travellers) if total is not None and travellers else None,
        "travellers": travellers, "days": days, "nights": nights,
        "complete": has_flight and has_hotel,
        "assumptions": assumptions.as_dict(),
        "converted": None,
    }
    target = (assumptions.convert_to or "").upper()
    if target and target != currency and rates and convert_fn:
        conv = {i["category"]: convert_fn(i["amount"], currency, target, rates) for i in items}
        total_c = convert_fn(total, currency, target, rates) if total is not None else None
        if total_c is not None:
            result["converted"] = {
                "currency": target, "total": total_c, "items": conv,
                "per_person": (total_c / travellers) if travellers else None,
                "rate": convert_fn(1.0, currency, target, rates),
                "updated": rates.get("updated"), "source": rates.get("source"),
            }
    return result
