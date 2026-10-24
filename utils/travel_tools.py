"""The tool box of the AI travel agent.

Each tool is a small, safe function that returns a JSON-friendly dict and NEVER raises: on a
problem it returns {"error": "..."} so the AI model can read the message and recover
(ask the person a question, fix a date, try again) instead of crashing the conversation.

`TravelTools` owns three things:
  * the shared TripState (what the trip currently looks like),
  * the latest result of each search (so nothing is searched twice and staleness is known),
  * a trace of every tool call (shown in the UI so people can see what the agent did).
"""

from __future__ import annotations

import inspect
import json
import threading
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable, Dict, List, Optional

from agents.flight_agent import FlightAgent
from agents.hotel_agent import HotelAgent
from . import travel_apis
from .config import logger, redact
from .recommendations import rule_based_recommendations
from .report_data import build_report
from .serp_client import ProviderError
from .trip_costs import calculate_trip_cost
from .trip_state import DEPENDS_ON, TripState, describe_changes

MAX_SHOWN_FLIGHTS = 8
MAX_SHOWN_HOTELS = 8
MAX_TOOL_OUTPUT_CHARS = 6000


@dataclass
class ToolCall:
    name: str
    arguments: Dict[str, Any]
    ok: bool
    seconds: float
    result: Dict[str, Any]
    cached: bool = False
    source: str = "agent"  # "agent" (chosen by the AI model) or "workflow" (fixed plan)
    at: float = field(default_factory=time.time)

    @property
    def preview(self) -> str:
        if not self.ok:
            return str(self.result.get("error"))
        bits = []
        for key in ("count", "found", "converted", "total", "changed"):
            if key in self.result:
                bits.append(f"{key}={self.result[key]}" if not isinstance(self.result[key], (dict, list)) else f"{key}={len(self.result[key])}")
        return ", ".join(bits) or "ok"


def shrink(result: Dict[str, Any], limit: int = MAX_TOOL_OUTPUT_CHARS) -> Dict[str, Any]:
    """Keep a tool result small enough for the model's context by dropping the tail of the longest list."""
    result = dict(result)
    for _ in range(200):
        if len(json.dumps(result, default=str, ensure_ascii=False)) <= limit:
            return result
        longest = max(((k, v) for k, v in result.items() if isinstance(v, list) and len(v) > 1), key=lambda kv: len(kv[1]), default=None)
        if not longest:
            break
        result[longest[0]] = longest[1][:-1]
        result["truncated"] = True
    return result


# ------------------------------------------------------------------ schemas
def _fn(name: str, description: str, properties: Dict[str, Any], required: Optional[List[str]] = None) -> Dict[str, Any]:
    return {"type": "function", "function": {"name": name, "description": description,
                                              "parameters": {"type": "object", "properties": properties, "required": required or []}}}


TOOL_SPECS: List[Dict[str, Any]] = [
    _fn(
        "update_trip_details",
        "Save or change details of the trip in the shared trip memory. Call this FIRST whenever the person gives or changes "
        "a requirement (cities, dates, travellers, budget, hotel stars, interests...). Only pass the fields that changed. "
        "The result lists which earlier search results are now stale and must be searched again.",
        {
            "origin": {"type": "string", "description": "Departure city or 3-letter airport code, e.g. 'Madrid' or 'MAD'"},
            "destination": {"type": "string", "description": "Arrival city or 3-letter airport code"},
            "stay_city": {"type": "string", "description": "Only if the hotel is in a different city than the arrival airport's city. Empty string resets it."},
            "departure_date": {"type": "string", "description": "YYYY-MM-DD"},
            "return_date": {"type": "string", "description": "YYYY-MM-DD, must be after departure"},
            "adults": {"type": "integer"}, "children": {"type": "integer"},
            "children_ages": {"type": "array", "items": {"type": "integer"}, "description": "One age (0-17) per child"},
            "rooms": {"type": "integer"},
            "currency": {"type": "string", "description": "3-letter currency for prices, e.g. USD, EUR, BDT"},
            "budget": {"type": "number", "description": "Total trip budget in the trip currency. 0 clears it."},
            "hotel_stars": {"type": "string", "description": "Hotel star classes, e.g. '4' or '4,5'"},
            "interests": {"type": "array", "items": {"type": "string"}, "description": "e.g. ['museums','food']"},
            "max_stops": {"type": "integer", "description": "Flights: 0 = any, 1 = nonstop only, 2 = at most 1 stop, 3 = at most 2 stops"},
        },
    ),
    _fn("search_flights",
        "Search round-trip flights for the current trip (uses origin, destination, dates, travellers, stops from the trip memory). "
        "Returns up to 8 options with prices, airlines, duration and stops. Needs no arguments.", {}),
    _fn("search_hotels",
        "Search hotels for the current trip (stay city, dates, guests, rooms, star class from the trip memory). "
        "Returns up to 8 options with rating, nightly price, total price and amenities. Needs no arguments.", {}),
    _fn("find_attractions",
        "Find tourist attractions and places to visit in the stay city. Optionally pass a category such as 'museums', 'beaches' or "
        "'family activities'; without it the person's saved interests are used.",
        {"category": {"type": "string"}}),
    _fn("get_weather",
        "Weather for the trip dates in the stay city. A real forecast when the dates are within about 2 weeks; otherwise the "
        "typical weather from the same dates last year (the result says which). Needs no arguments.", {}),
    _fn("web_search",
        "Search the web for anything the other tools do not cover: visa or entry rules, events, local transport, opening hours, safety, "
        "recent news. Pass a precise query.",
        {"query": {"type": "string"}, "num_results": {"type": "integer", "description": "1-10, default 5"}}, ["query"]),
    _fn("convert_currency",
        "Convert an amount between currencies with live exchange rates. ALWAYS use this instead of converting in your head.",
        {"amount": {"type": "number"}, "from_currency": {"type": "string"}, "to_currency": {"type": "string"}},
        ["amount", "from_currency", "to_currency"]),
    _fn("calculate_trip_cost",
        "Exact trip cost from the latest flight and hotel results plus any daily costs the person provided. ALWAYS use this instead of "
        "adding prices yourself. By default it uses the cheapest flight and cheapest hotel; pass option numbers to price a specific "
        "combination. Optionally convert the total to another currency and compare with the saved budget.",
        {
            "flight_option": {"type": "integer"}, "hotel_option": {"type": "integer"},
            "food_per_person_per_day": {"type": "number"}, "activities_per_person_per_day": {"type": "number"},
            "local_transport_per_day": {"type": "number"},
            "other_costs": {"type": "array", "items": {"type": "object", "properties": {"label": {"type": "string"}, "amount": {"type": "number"}}}},
            "convert_to": {"type": "string", "description": "3-letter currency to also show the total in"},
        }),
]

# Plain-language table used by the UI ("how the tools work together").
TOOL_CATALOG = [
    {"tool": "update_trip_details", "purpose": "Remember / change trip requirements", "data": "Trip memory (no API)", "needs_key": "No"},
    {"tool": "search_flights", "purpose": "Flight options and prices", "data": "SerpAPI - Google Flights", "needs_key": "SERPAPI_API_KEY"},
    {"tool": "search_hotels", "purpose": "Hotel and accommodation options", "data": "SerpAPI - Google Hotels", "needs_key": "SERPAPI_API_KEY"},
    {"tool": "find_attractions", "purpose": "Tourist attractions", "data": "SerpAPI - Google Maps", "needs_key": "SERPAPI_API_KEY"},
    {"tool": "get_weather", "purpose": "Forecast or typical weather", "data": "Open-Meteo", "needs_key": "No"},
    {"tool": "web_search", "purpose": "Visas, events, tips, anything else", "data": "SerpAPI - Google Search", "needs_key": "SERPAPI_API_KEY"},
    {"tool": "convert_currency", "purpose": "Live exchange rates", "data": "open.er-api.com / Frankfurter", "needs_key": "No"},
    {"tool": "calculate_trip_cost", "purpose": "Exact cost arithmetic and budget check", "data": "Latest flight + hotel results", "needs_key": "No"},
]

_STATE_FIELD_NAMES = {"stay_city": "hotel_city", "hotel_stars": "hotel_class", "max_stops": "stops"}
_ALLOWED_UPDATE_FIELDS = (
    "origin", "destination", "stay_city", "departure_date", "return_date", "adults", "children", "children_ages",
    "rooms", "currency", "budget", "hotel_stars", "interests", "max_stops",
)


class TravelTools:
    def __init__(self, state: Optional[TripState] = None, today: Optional[date] = None):
        self.state = state or TripState()
        self.today = today
        self.results: Dict[str, Dict[str, Any]] = {}   # "flights" | "hotels" | "weather" | "attractions" | "tips"
        self.last_cost: Optional[Dict[str, Any]] = None
        self.trace: List[ToolCall] = []
        self._lock = threading.RLock()
        self._registry: Dict[str, Callable[..., Dict[str, Any]]] = {
            "update_trip_details": self.update_trip_details,
            "search_flights": self.search_flights,
            "search_hotels": self.search_hotels,
            "find_attractions": self.find_attractions,
            "get_weather": self.get_weather,
            "web_search": self.web_search,
            "search_tips": self.search_tips,  # used by the workflow only; not offered to the AI model
            "convert_currency": self.convert_currency,
            "calculate_trip_cost": self.calculate_trip_cost,
        }

    # ------------------------------------------------------------ public API
    @staticmethod
    def specs() -> List[Dict[str, Any]]:
        return TOOL_SPECS

    def call(self, name: str, arguments: Optional[Dict[str, Any]] = None, source: str = "agent") -> Dict[str, Any]:
        """Run one tool. Never raises; records the call in the trace."""
        args = arguments if isinstance(arguments, dict) else {}
        started = time.time()
        cached_before = False
        fn = self._registry.get(name)
        if fn is None:
            result = {"error": f"Unknown tool '{name}'. Available tools: {', '.join(self._registry)}."}
        else:
            try:
                inspect.signature(fn).bind(**args)
            except TypeError as exc:
                result = {"error": f"Bad arguments for {name}: {exc}"}
            else:
                try:
                    result = fn(**args)
                    cached_before = bool(result.pop("_cached", False))
                except ProviderError as exc:
                    result = {"error": redact(exc)}
                except Exception as exc:  # a tool bug must not end the conversation
                    logger.warning("Tool %s crashed: %s", name, redact(exc))
                    result = {"error": f"The {name} tool failed unexpectedly: {redact(exc)}"}
        call = ToolCall(name, args, "error" not in result, round(time.time() - started, 2), result, cached_before, source)
        with self._lock:
            self.trace.append(call)
        return result

    def is_stale(self, key: str) -> bool:
        with self._lock:
            entry = self.results.get(key)
            return entry is None or entry["signature"] != self.state.signature(key)

    def stale_results(self) -> List[str]:
        """Searches we have results for, but whose inputs have changed since."""
        with self._lock:
            return [k for k in DEPENDS_ON if k in self.results and self.is_stale(k)]

    def data(self, key: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            entry = self.results.get(key)
            return entry["data"] if entry else None

    def status_lines(self) -> List[str]:
        """What is on file - injected into the agent's instructions so it never re-searches blindly."""
        lines = []
        labels = {"flights": "flights", "hotels": "hotels", "weather": "weather", "attractions": "attractions", "tips": "travel tips"}
        for key, label in labels.items():
            entry = self.results.get(key)
            if entry is None:
                lines.append(f"- {label}: not searched yet")
            elif self.is_stale(key):
                lines.append(f"- {label}: STALE (trip details changed since the search) - search again before using")
            else:
                lines.append(f"- {label}: up to date")
        return lines

    def report(self) -> Dict[str, Any]:
        """The same report dict used by the PDF / Excel / Word exports, built from the latest results."""
        s = self.state
        request = {
            "origin": s.origin, "destination": s.destination, "origin_city": s.origin_city,
            "destination_city": s.destination_city, "city": s.hotel_city, "departure_date": s.departure_date,
            "return_date": s.return_date, "adults": s.adults, "children": s.children, "children_ages": s.hotel_ages(),
            "rooms": s.rooms, "stops": s.stops, "currency": s.currency,
        }
        flights, hotels = self.data("flights"), self.data("hotels")
        return build_report(request, flights, hotels, rule_based_recommendations(flights, hotels))

    def reset(self) -> None:
        with self._lock:
            self.state = TripState()
            self.results.clear()
            self.trace.clear()
            self.last_cost = None

    # ------------------------------------------------------------ helpers
    def _store(self, key: str, data: Dict[str, Any]) -> None:
        with self._lock:
            self.results[key] = {"data": data, "signature": self.state.signature(key), "at": time.time()}

    def _missing(self, key: str) -> Optional[Dict[str, Any]]:
        missing = self.state.missing_for(key)
        if not missing:
            return None
        names = {"stay_city": "destination city", "departure_date": "departure date", "return_date": "return date"}
        return {"error": "Missing trip details: " + ", ".join(names.get(m, m) for m in missing)
                + ". Ask the person for them (or call update_trip_details) before searching."}

    # ------------------------------------------------------------ the tools
    def update_trip_details(self, **fields: Any) -> Dict[str, Any]:
        unknown = [k for k in fields if k not in _ALLOWED_UPDATE_FIELDS]
        mapped = {_STATE_FIELD_NAMES.get(k, k): v for k, v in fields.items() if k in _ALLOWED_UPDATE_FIELDS}
        outcome = self.state.update(today=self.today, **mapped)
        rejected = dict(outcome["rejected"])
        for name in unknown:
            rejected[name] = f"Unknown field. Valid fields: {', '.join(_ALLOWED_UPDATE_FIELDS)}."
        changed_text = describe_changes(outcome["changed"])
        stale = self.stale_results()
        return {
            "changed": changed_text, "rejected": rejected, "notes": outcome["notes"],
            "trip": self.state.summary(),
            "results_now_stale": stale,
            "next_step": ("Search again: " + ", ".join(stale)) if stale else ("Nothing to re-search." if changed_text else "No change."),
            "still_missing": {k: self.state.missing_for(k) for k in ("flights", "hotels") if self.state.missing_for(k)},
        }

    def search_flights(self) -> Dict[str, Any]:
        if (err := self._missing("flights")):
            return err
        if not self.is_stale("flights"):
            return {**self._flights_view(), "_cached": True}
        s = self.state
        agent = FlightAgent()
        raw = agent.search_flights({
            "origin": s.origin, "destination": s.destination, "departure_date": s.departure_date, "return_date": s.return_date,
            "adults": s.adults, "children": s.children, "stops": s.stops, "currency": s.currency,
        })
        self._store("flights", agent._parse_flight_data(raw, currency=s.currency))
        return self._flights_view()

    def _flights_view(self) -> Dict[str, Any]:
        rows = self.report()["flights"]
        if not rows:
            return {"count": 0, "flights": [], "note": "No flights were returned. Try different dates, airports or allow more stops."}
        ordered = sorted(rows, key=lambda f: (f["price"] is None, f["price"] or 0))
        priced = [f for f in rows if f["price"] is not None]
        fastest = min((f for f in rows if f.get("duration_minutes")), key=lambda f: f["duration_minutes"], default=None)
        return {
            "count": len(rows), "showing": min(len(rows), MAX_SHOWN_FLIGHTS), "currency": self.state.currency,
            "cheapest_option": min(priced, key=lambda f: f["price"])["option"] if priced else None,
            "fastest_option": fastest["option"] if fastest else None,
            "flights": [
                {"option": f["option"], "airline": f["airline"], "price": f["price"], "stops": f["stops"], "duration": f["duration"],
                 "departs": f["departure"], "arrives": f["arrival"], "from": f["departure_airport"], "to": f["arrival_airport"],
                 "google_top_pick": bool(f["top_pick"])}
                for f in ordered[:MAX_SHOWN_FLIGHTS]
            ],
            "booking_link": next((f["booking_url"] for f in rows if f["booking_url"]), None),
            "note": "Prices are search results, not confirmed fares; confirm whether they are per person on the booking page.",
        }

    def search_hotels(self) -> Dict[str, Any]:
        if (err := self._missing("hotels")):
            return err
        if not self.is_stale("hotels"):
            return {**self._hotels_view(), "_cached": True}
        s = self.state
        agent = HotelAgent()
        raw = agent.search_hotels({
            "location": s.stay_city, "check_in": s.departure_date, "check_out": s.return_date, "adults": s.adults,
            "children": s.children, "children_ages": s.hotel_ages(), "rooms": s.rooms, "hotel_class": s.hotel_class, "currency": s.currency,
        })
        parsed = agent._parse_hotel_data(raw, currency=s.currency)
        parsed["search_city"] = s.stay_city
        self._store("hotels", parsed)
        return self._hotels_view()

    def _hotels_view(self) -> Dict[str, Any]:
        rows = self.report()["hotels"]
        if not rows:
            return {"count": 0, "hotels": [], "city": self.state.stay_city, "note": "No hotels were returned. Try other dates or fewer filters."}
        ordered = sorted(rows, key=lambda h: (h["rating"] is None, -(h["rating"] or 0), h["price_per_night"] if h["price_per_night"] is not None else 10**9))
        priced = [h for h in rows if h["price_per_night"] is not None]
        rated = [h for h in rows if h["rating"] is not None]
        return {
            "count": len(rows), "showing": min(len(rows), MAX_SHOWN_HOTELS), "city": self.state.stay_city,
            "currency": self.state.currency, "nights": self.state.nights,
            "cheapest_option": min(priced, key=lambda h: h["price_per_night"])["option"] if priced else None,
            "top_rated_option": max(rated, key=lambda h: (h["rating"], h["reviews"] or 0))["option"] if rated else None,
            "hotels": [
                {"option": h["option"], "name": h["name"], "stars": h["hotel_class"], "rating": h["rating"], "reviews": h["reviews"],
                 "per_night": h["price_per_night"], "total": h["total_price"], "amenities": (h["amenities_list"] or [])[:5], "link": h["booking_url"]}
                for h in ordered[:MAX_SHOWN_HOTELS]
            ],
            "assumptions": ([f"Children's ages were not all given; age {self.state.hotel_ages()[-1]} was assumed where unknown."]
                            if self.state.children and len(self.state.children_ages) != self.state.children else []),
        }

    def find_attractions(self, category: str = "") -> Dict[str, Any]:
        if (err := self._missing("attractions")):
            return err
        city = self.state.stay_city
        if category and category.strip():  # one-off question: not stored as "the" attractions result
            found = travel_apis.find_attractions(city, category.strip())
            return {"city": city, "category": category.strip(), "count": len(found["places"]), "places": found["places"]}
        if not self.is_stale("attractions"):
            return {**self._attractions_view(), "_cached": True}
        interests = self.state.interests[:3]
        places: List[Dict[str, Any]] = []
        seen = set()
        for interest in interests or [""]:
            for p in travel_apis.find_attractions(city, interest, limit=8)["places"]:
                if p["name"] not in seen:
                    seen.add(p["name"])
                    places.append({**p, "interest": interest or None})
        self._store("attractions", {"city": city, "places": places, "source": "SerpAPI - Google Maps"})
        return self._attractions_view()

    def _attractions_view(self) -> Dict[str, Any]:
        data = self.data("attractions") or {}
        places = data.get("places") or []
        return {"city": data.get("city"), "count": len(places), "places": [
            {k: p.get(k) for k in ("name", "type", "rating", "reviews", "address", "description", "interest") if p.get(k) is not None}
            for p in places[:12]
        ]}

    def get_weather(self) -> Dict[str, Any]:
        if (err := self._missing("weather")):
            return err
        if not self.is_stale("weather"):
            return {**self._weather_view(), "_cached": True}
        s = self.state
        data = travel_apis.get_weather(s.stay_city, date.fromisoformat(s.departure_date), date.fromisoformat(s.return_date), today=self.today)
        self._store("weather", data)
        return self._weather_view()

    def _weather_view(self) -> Dict[str, Any]:
        data = self.data("weather") or {}
        return {k: data.get(k) for k in ("city", "mode", "note", "summary", "units")} | {"daily": [
            {"date": d["date"], "condition": d["condition"], "high": d["temp_max_c"], "low": d["temp_min_c"], "rain_mm": d["rain_mm"]}
            for d in (data.get("daily") or [])[:16]
        ]}

    def search_tips(self) -> Dict[str, Any]:
        """Workflow helper (not offered to the AI model): one web search for local tips, stored for staleness tracking."""
        if (err := self._missing("tips")):
            return err
        if not self.is_stale("tips"):
            return {**self._tips_view(), "_cached": True}
        found = travel_apis.web_search(f"{self.state.stay_city} travel tips best areas to stay local transport", 5)
        self._store("tips", found)
        return self._tips_view()

    def _tips_view(self) -> Dict[str, Any]:
        data = self.data("tips") or {}
        return {"count": len(data.get("results") or []), **{k: data.get(k) for k in ("query", "quick_answer", "results")}}

    def web_search(self, query: str, num_results: int = 5) -> Dict[str, Any]:
        found = travel_apis.web_search(query, num_results)
        return {"count": len(found["results"]), **found}

    def convert_currency(self, amount: float, from_currency: str, to_currency: str) -> Dict[str, Any]:
        return travel_apis.convert_currency(amount, from_currency, to_currency)

    def calculate_trip_cost(
        self, flight_option: Optional[int] = None, hotel_option: Optional[int] = None,
        food_per_person_per_day: float = 0, activities_per_person_per_day: float = 0, local_transport_per_day: float = 0,
        other_costs: Optional[List[Dict[str, Any]]] = None, convert_to: str = "",
    ) -> Dict[str, Any]:
        if self.data("flights") is None and self.data("hotels") is None:
            return {"error": "Nothing to price yet: search flights and/or hotels first."}
        stale = [k for k in ("flights", "hotels") if k in self.results and self.is_stale(k)]
        report = self.report()
        cost = calculate_trip_cost(
            report["flights"], report["hotels"], self.state.nights, self.state.travellers, self.state.currency,
            flight_option, hotel_option, food_per_person_per_day, activities_per_person_per_day,
            local_transport_per_day, other_costs, self.state.budget,
        )
        if stale:
            cost["warnings"].append("These results are out of date because the trip changed: " + ", ".join(stale) + ". Search again for an accurate price.")
        target = (convert_to or "").strip().upper()
        if target and target != self.state.currency and cost["total"] is not None:
            try:
                fx = travel_apis.convert_currency(cost["total"], self.state.currency, target)
                cost["converted"] = {"currency": target, "total": fx["converted"], "per_person": round(fx["converted"] / max(1, self.state.travellers), 2),
                                     "rate": fx["rate"], "as_of": fx["as_of"], "source": fx["source"]}
            except ProviderError as exc:
                cost["warnings"].append(f"Could not convert to {target}: {redact(exc)}")
        self.last_cost = cost
        return cost
