"""Recommendations built ONLY from real search results.

* `rule_based_recommendations` - always available, no AI needed.
* `build_llm_prompt` / `parse_llm_recommendations` - optional AI layer. The AI
  may only point at option numbers that exist; anything else is discarded.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from .config import DEFAULT_CURRENCY
from .report_data import fmt_money

MAX_OPTIONS_FOR_AI = 15


def _flights(result: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return (result or {}).get("recommended_flights") or []


def _hotels(result: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return (result or {}).get("recommended_hotels") or []


def rule_based_recommendations(
    flights_result: Optional[Dict[str, Any]], hotels_result: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    flights, hotels = _flights(flights_result), _hotels(hotels_result)
    best_flight = best_hotel = None

    priced = [(i, f) for i, f in enumerate(flights, start=1) if f.get("price_value") is not None]
    if priced:
        i, f = min(priced, key=lambda p: (p[1]["price_value"], p[1].get("stops") or 0))
        parts = [f"lowest price returned ({fmt_money(f['price_value'], f.get('currency', DEFAULT_CURRENCY))})"]
        if f.get("duration"):
            parts.append(f"duration {f['duration']}")
        if f.get("stops") is not None:
            parts.append("nonstop" if f["stops"] == 0 else f"{f['stops']} stop(s)")
        best_flight = {"option": i, "reason": "Chosen because it is the " + ", ".join(parts) + "."}

    rated = [(i, h) for i, h in enumerate(hotels, start=1) if h.get("rating") is not None]
    if rated:
        def hotel_key(p):
            h = p[1]
            price = h.get("price_per_night_value")
            return (-h["rating"], price if price is not None else float("inf"))

        i, h = min(rated, key=hotel_key)
        reason = f"Chosen because it has the highest guest rating returned ({h['rating']:.1f})"
        if h.get("price_per_night_value") is not None:
            reason += f" at {fmt_money(h['price_per_night_value'], h.get('currency', DEFAULT_CURRENCY))} per night"
        best_hotel = {"option": i, "reason": reason + "."}

    summary = None
    if best_flight or best_hotel:
        summary = "Automatic summary based only on the returned results (no AI model used)."
    return {
        "source": "rule_based",
        "source_label": "Rule-based summary (no AI model)",
        "best_flight": best_flight,
        "best_hotel": best_hotel,
        "summary": summary,
        "warnings": [],
    }


def build_llm_prompt(
    flights_result: Optional[Dict[str, Any]], hotels_result: Optional[Dict[str, Any]]
) -> str:
    flights = [
        {
            "option": i,
            "airline": f.get("airline"),
            "price": f.get("price_value"),
            "currency": f.get("currency"),
            "duration": f.get("duration"),
            "stops": f.get("stops"),
            "departure": f.get("departure"),
            "arrival": f.get("arrival"),
        }
        for i, f in enumerate(_flights(flights_result), start=1)
    ][:MAX_OPTIONS_FOR_AI]
    hotels = [
        {
            "option": i,
            "name": h.get("name"),
            "rating": h.get("rating"),
            "reviews": h.get("reviews"),
            "price_per_night": h.get("price_per_night_value"),
            "total_price": h.get("total_price_value"),
            "currency": h.get("currency"),
            "hotel_class": h.get("hotel_class"),
        }
        for i, h in enumerate(_hotels(hotels_result), start=1)
    ][:MAX_OPTIONS_FOR_AI]
    return (
        "Below are REAL search results as JSON. Pick the best flight and the best hotel.\n"
        "Rules: use only the data below; never invent prices, ratings or facts; do not do any "
        "cost arithmetic; refer to options by their 'option' number; use null if there are no "
        "options of that kind.\n"
        'Reply with ONLY this JSON object: {"best_flight_option": <int|null>, '
        '"best_flight_reason": <string>, "best_hotel_option": <int|null>, '
        '"best_hotel_reason": <string>, "summary": <string, max 3 sentences>}\n\n'
        f"FLIGHTS: {json.dumps(flights, ensure_ascii=False)}\n"
        f"HOTELS: {json.dumps(hotels, ensure_ascii=False)}\n"
    )


def parse_llm_recommendations(
    parsed: Dict[str, Any], n_flights: int, n_hotels: int, model_name: str = "AI model"
) -> Optional[Dict[str, Any]]:
    """Validate the AI's JSON. Returns None when it is unusable."""
    if not isinstance(parsed, dict) or parsed.get("error"):
        return None

    def pick(option_key: str, reason_key: str, limit: int) -> Optional[Dict[str, Any]]:
        option = parsed.get(option_key)
        reason = parsed.get(reason_key)
        if isinstance(option, bool) or not isinstance(option, int) or not 1 <= option <= limit:
            return None
        return {"option": option, "reason": str(reason).strip() if reason else ""}

    best_flight = pick("best_flight_option", "best_flight_reason", n_flights)
    best_hotel = pick("best_hotel_option", "best_hotel_reason", n_hotels)
    summary = parsed.get("summary")
    summary = str(summary).strip() if isinstance(summary, str) and summary.strip() else None
    if not (best_flight or best_hotel or summary):
        return None
    return {
        "source": "ai",
        "source_label": f"AI-generated recommendations ({model_name}), based on the returned results",
        "best_flight": best_flight,
        "best_hotel": best_hotel,
        "summary": summary,
        "warnings": [],
    }
