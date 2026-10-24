"""Trip cost calculation. Plain arithmetic: an AI model should never do this sum in its head."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .report_data import fmt_money


def _hotel_total(hotel: Dict[str, Any], nights: Optional[int]) -> Optional[tuple]:
    if hotel.get("total_price") is not None:
        return hotel["total_price"], "Total stay price returned by Google Hotels"
    if hotel.get("price_per_night") is not None and nights:
        return hotel["price_per_night"] * nights, f"Calculated: nightly rate x {nights} nights (no total returned)"
    return None


def calculate_trip_cost(
    flights: List[Dict[str, Any]],
    hotels: List[Dict[str, Any]],
    nights: Optional[int],
    travellers: int,
    currency: str,
    flight_option: Optional[int] = None,
    hotel_option: Optional[int] = None,
    food_per_person_per_day: float = 0.0,
    activities_per_person_per_day: float = 0.0,
    local_transport_per_day: float = 0.0,
    other_costs: Optional[List[Dict[str, Any]]] = None,
    budget: Optional[float] = None,
) -> Dict[str, Any]:
    """Add up the chosen flight + hotel + any daily costs the person gave.

    `flights` / `hotels` are the normalised report rows (each has an `option` number).
    No cost is ever guessed: daily costs are 0 unless the person supplied them.
    Without a chosen option the cheapest priced flight / hotel is used, and says so.
    """
    items: List[Dict[str, Any]] = []
    warnings: List[str] = []
    days = (nights + 1) if nights else None

    flight = None
    priced_flights = [f for f in flights if f.get("price") is not None]
    if flight_option is not None:
        flight = next((f for f in flights if f["option"] == flight_option), None)
        if flight is None:
            warnings.append(f"Flight option {flight_option} does not exist.")
        elif flight.get("price") is None:
            warnings.append(f"Flight option {flight_option} has no price.")
            flight = None
    elif priced_flights:
        flight = min(priced_flights, key=lambda f: f["price"])
    if flight:
        chosen = "chosen" if flight_option is not None else "cheapest priced"
        items.append({
            "label": f"Flight: {flight.get('airline') or 'n/a'} (option {flight['option']}, {chosen})",
            "amount": float(flight["price"]),
            "basis": "Price returned by Google Flights for the whole search - confirm whether it is per person on the booking page",
        })

    hotel = None
    priced_hotels = [(h, _hotel_total(h, nights)) for h in hotels]
    priced_hotels = [(h, t) for h, t in priced_hotels if t]
    if hotel_option is not None:
        hotel = next((h for h in hotels if h["option"] == hotel_option), None)
        if hotel is None:
            warnings.append(f"Hotel option {hotel_option} does not exist.")
        elif not _hotel_total(hotel, nights):
            warnings.append(f"Hotel option {hotel_option} has no usable price.")
            hotel = None
    elif priced_hotels:
        hotel = min(priced_hotels, key=lambda p: p[1][0])[0]
    if hotel:
        amount, basis = _hotel_total(hotel, nights)  # type: ignore[misc]
        chosen = "chosen" if hotel_option is not None else "cheapest priced"
        items.append({"label": f"Hotel: {hotel.get('name')} (option {hotel['option']}, {chosen})", "amount": float(amount), "basis": basis})

    def daily(label: str, rate: float, per_person: bool) -> None:
        if not rate:
            return
        if not days:
            warnings.append(f"{label} skipped: trip dates are missing.")
            return
        multiplier = travellers if per_person else 1
        who = f" x {travellers} traveller(s)" if per_person else ""
        items.append({"label": label, "amount": float(rate) * days * multiplier, "basis": f"{fmt_money(rate, currency)} x {days} days{who} (rate given by you)"})

    daily("Food", food_per_person_per_day, True)
    daily("Activities", activities_per_person_per_day, True)
    daily("Local transport", local_transport_per_day, False)
    for extra in other_costs or []:
        try:
            amount = float(extra.get("amount"))
        except (TypeError, ValueError):
            warnings.append(f"Ignored an extra cost without a valid amount: {extra.get('label')!r}.")
            continue
        items.append({"label": str(extra.get("label") or "Other cost"), "amount": amount, "basis": "Amount given by you"})

    total = round(sum(i["amount"] for i in items), 2) if items else None
    result: Dict[str, Any] = {
        "currency": currency,
        "items": [{**i, "amount": round(i["amount"], 2)} for i in items],
        "total": total,
        "per_person": round(total / travellers, 2) if total is not None and travellers else None,
        "includes_flight": flight is not None,
        "includes_hotel": hotel is not None,
        "complete": flight is not None and hotel is not None,
        "warnings": warnings,
        "not_included": [
            "Baggage, seat and other airline fees", "Airport transfers", "Visas, insurance and vaccinations",
            "Hotel taxes or city fees not in the provider's price", "Card or currency-exchange fees",
        ],
    }
    if budget and total is not None:
        diff = round(budget - total, 2)
        result["budget"] = {"amount": budget, "status": "within budget" if diff >= 0 else "over budget", "difference": abs(diff)}
    return result
