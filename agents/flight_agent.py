from typing import Dict, Any, List, Optional
from datetime import datetime

from .base_agent import BaseAgent
from utils.config import DEFAULT_CURRENCY
from utils.serp_client import serpapi_search, NoResultsError


def _to_number(value: Any) -> Optional[float]:
    """Return a float for real numbers; None for missing/invalid values."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _format_duration(minutes: Any) -> Optional[str]:
    minutes = _to_number(minutes)
    if minutes is None or minutes <= 0:
        return None
    minutes = int(minutes)
    return f"{minutes // 60}h {minutes % 60}m"


def _join_unique(values: List[Optional[str]]) -> Optional[str]:
    seen: List[str] = []
    for v in values:
        if v and v not in seen:
            seen.append(str(v))
    return ", ".join(seen) if seen else None


class FlightAgent(BaseAgent):
    def __init__(self):
        super().__init__(
            name="FlightAgent",
            instructions="""Search and analyze flight options.
            Consider: price, duration, airline reputation, and convenience.
            Provide detailed flight information with airline logos and booking links.
            Return results in HTML format with pricing, schedules, and airline details.""",
        )

    async def run(self, messages: list) -> Dict[str, Any]:
        """Search flights and return parsed, structured results."""
        search_params = self._load_payload(messages)
        data = self.search_flights(search_params)
        return self._parse_flight_data(data, currency=search_params.get("currency", DEFAULT_CURRENCY))

    def search_flights(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Call SerpAPI Google Flights. Raises ProviderError on real failures.

        `stops`: 0 = any, 1 = nonstop only, 2 = 1 stop or fewer, 3 = 2 stops or fewer.
        (The original code always used 1, i.e. nonstop only; that is still the
        default here but the UI now lets the user change it.)
        """
        search_params = {
            "engine": "google_flights",
            "hl": "en",
            "gl": "us",
            "departure_id": params.get("origin", ""),
            "arrival_id": params.get("destination", ""),
            "outbound_date": params.get("departure_date", ""),
            "return_date": params.get("return_date", ""),
            "currency": params.get("currency", DEFAULT_CURRENCY),
            "adults": params.get("adults", 1),
            "children": params.get("children", 0),
            "infants_in_seat": params.get("infants_in_seat", 0),
            "infants_on_lap": params.get("infants_on_lap", 0),
            "stops": params.get("stops", 1),
        }
        try:
            return serpapi_search(search_params)
        except NoResultsError:
            return {}  # treated as "0 flights", not as a failure

    def _parse_flight_data(self, data: Dict[str, Any], currency: str = DEFAULT_CURRENCY) -> Dict[str, Any]:
        """Turn the SerpAPI response into one row per itinerary.

        Fixes vs. the original: reads `best_flights` as well as `other_flights`,
        creates one row per itinerary (not one per leg, which repeated the full
        price on every leg), never invents a price, and keeps numeric values.
        """
        if not isinstance(data, dict):
            data = {}
        metadata = data.get("search_metadata") or {}
        search_url = metadata.get("google_flights_url")

        rows: List[Dict[str, Any]] = []
        for group_key, is_best in (("best_flights", True), ("other_flights", False)):
            for option in data.get(group_key) or []:
                legs = [leg for leg in (option.get("flights") or []) if isinstance(leg, dict)]
                if not legs:
                    continue
                first, last = legs[0], legs[-1]
                total_minutes = _to_number(option.get("total_duration"))
                if total_minutes is None:
                    leg_minutes = [_to_number(leg.get("duration")) for leg in legs]
                    if all(m is not None for m in leg_minutes):
                        total_minutes = sum(leg_minutes)  # type: ignore[arg-type]
                price = _to_number(option.get("price"))
                rows.append(
                    {
                        "airline": _join_unique([leg.get("airline") for leg in legs]),
                        "airlines": [str(a) for a in dict.fromkeys(leg.get("airline") for leg in legs) if a],
                        "flight_number": _join_unique([leg.get("flight_number") for leg in legs]),
                        "departure": (first.get("departure_airport") or {}).get("time"),
                        "arrival": (last.get("arrival_airport") or {}).get("time"),
                        "departure_airport": (first.get("departure_airport") or {}).get("id"),
                        "arrival_airport": (last.get("arrival_airport") or {}).get("id"),
                        "duration": _format_duration(total_minutes),
                        "duration_minutes": int(total_minutes) if total_minutes else None,
                        "stops": len(legs) - 1,
                        "price": f"{price:,.0f}" if price is not None else None,
                        "price_value": price,
                        "currency": currency,
                        "logo_url": option.get("airline_logo") or first.get("airline_logo"),
                        # NOTE: this is the Google Flights *search* link for the whole
                        # query, not a deep link to one specific fare.
                        "booking_url": search_url,
                        "is_top_pick": is_best,
                        "trip_type": option.get("type"),
                    }
                )

        return {
            "recommended_flights": rows,
            "search_timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "number_of_options": len(rows),
            "source": "SerpAPI - Google Flights",
            "search_url": search_url,
        }
