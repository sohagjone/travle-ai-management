"""The agent's shared memory about the trip: ONE small object that every tool reads.

Why it exists: "make it a day longer" or "what's the weather there?" only makes sense if
the program remembers where "there" is. The chat history helps the AI model, but this
structured state is what the tools actually use - and it lets us tell exactly which
search results go stale when the person changes their mind.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from .airport_resolver import resolve_airport
from .config import DEFAULT_CURRENCY
from .validation import MAX_ROOMS, MAX_TRAVELLERS

DEFAULT_CHILD_AGE = 8

# Which trip fields each result depends on. Change one of these and that result is stale.
DEPENDS_ON: Dict[str, Tuple[str, ...]] = {
    "flights": ("origin", "destination", "departure_date", "return_date", "adults", "children", "stops", "currency"),
    "hotels": ("stay_city", "departure_date", "return_date", "adults", "children", "children_ages", "rooms", "hotel_class", "currency"),
    "weather": ("stay_city", "departure_date", "return_date"),
    "attractions": ("stay_city", "interests"),
    "tips": ("stay_city",),
}

_FIELD_LABELS = {
    "origin": "From", "destination": "To", "stay_city": "Stay city", "departure_date": "Departure",
    "return_date": "Return", "adults": "Adults", "children": "Children", "children_ages": "Children's ages",
    "rooms": "Rooms", "currency": "Currency", "budget": "Budget", "hotel_class": "Hotel stars",
    "interests": "Interests", "stops": "Stops",
}


@dataclass
class TripState:
    origin: str = ""            # IATA code
    origin_city: str = ""
    destination: str = ""       # IATA code
    destination_city: str = ""
    hotel_city: str = ""        # optional: stay somewhere other than the arrival city
    departure_date: str = ""    # YYYY-MM-DD
    return_date: str = ""
    adults: int = 1
    children: int = 0
    children_ages: List[int] = field(default_factory=list)
    rooms: int = 1
    currency: str = DEFAULT_CURRENCY
    budget: Optional[float] = None
    hotel_class: str = ""       # "3,4" = 3 and 4 stars
    interests: List[str] = field(default_factory=list)
    stops: int = 0              # 0 any, 1 nonstop, 2 <=1 stop, 3 <=2 stops

    # ------------------------------------------------------------ derived
    @property
    def stay_city(self) -> str:
        return self.hotel_city or self.destination_city

    @property
    def nights(self) -> Optional[int]:
        try:
            n = (date.fromisoformat(self.return_date) - date.fromisoformat(self.departure_date)).days
        except ValueError:
            return None
        return n if n > 0 else None

    @property
    def travellers(self) -> int:
        return self.adults + self.children

    def value(self, name: str) -> Any:
        return getattr(self, name)

    def signature(self, tool: str) -> str:
        """Fingerprint of every input a tool's result depends on."""
        return json.dumps({f: self.value(f) for f in DEPENDS_ON[tool]}, sort_keys=True, default=str)

    def missing_for(self, tool: str) -> List[str]:
        need = {
            "flights": ["origin", "destination", "departure_date", "return_date"],
            "hotels": ["stay_city", "departure_date", "return_date"],
            "weather": ["stay_city", "departure_date", "return_date"],
            "attractions": ["stay_city"],
            "tips": ["stay_city"],
        }[tool]
        return [f for f in need if not self.value(f)]

    def hotel_ages(self) -> List[int]:
        """One age per child (hotel prices need it); unknown ages default to 8."""
        ages = list(self.children_ages)[: self.children]
        return ages + [DEFAULT_CHILD_AGE] * (self.children - len(ages))

    # ------------------------------------------------------------ summaries
    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["stay_city"] = self.stay_city
        d["nights"] = self.nights
        return d

    def summary(self) -> str:
        if not (self.origin or self.destination or self.departure_date):
            return "No trip details yet."
        route = f"{self.origin_city or '?'} ({self.origin or '?'}) -> {self.destination_city or '?'} ({self.destination or '?'})"
        parts = [f"Route: {route}"]
        if self.hotel_city:
            parts.append(f"Staying in: {self.hotel_city}")
        parts.append(f"Dates: {self.departure_date or '?'} to {self.return_date or '?'}" + (f" ({self.nights} nights)" if self.nights else ""))
        who = f"{self.adults} adult(s)" + (f", {self.children} child(ren) aged {self.hotel_ages()}" if self.children else "")
        parts.append(f"Travellers: {who}; rooms: {self.rooms}")
        parts.append(f"Currency: {self.currency}" + (f"; budget: {self.budget:,.0f} {self.currency}" if self.budget else ""))
        if self.hotel_class:
            parts.append(f"Hotel stars: {self.hotel_class}")
        if self.interests:
            parts.append("Interests: " + ", ".join(self.interests))
        if self.stops:
            parts.append({1: "Flights: nonstop only", 2: "Flights: max 1 stop", 3: "Flights: max 2 stops"}.get(self.stops, ""))
        return "\n".join(p for p in parts if p)

    # ------------------------------------------------------------ updating
    def update(self, today: Optional[date] = None, **changes: Any) -> Dict[str, Any]:
        """Apply validated changes. Returns {"changed": {...}, "rejected": {...}, "notes": [...]}.

        Invalid values are rejected with a friendly message and the old value is kept, so a
        mistake by the person or the AI model can never leave the trip in a broken state.
        """
        today = today or date.today()
        changed: Dict[str, Dict[str, Any]] = {}
        rejected: Dict[str, str] = {}
        notes: List[str] = []

        def put(name: str, new: Any) -> None:
            old = self.value(name)
            if old != new:
                setattr(self, name, new)
                changed[name] = {"from": old, "to": new}

        def as_int(name: str, low: int, high: int) -> Optional[int]:
            raw = changes[name]
            try:
                if isinstance(raw, bool) or int(raw) != float(raw):
                    raise ValueError
                number = int(raw)
            except (TypeError, ValueError):
                rejected[name] = f"{_FIELD_LABELS[name]} must be a whole number."
                return None
            if not low <= number <= high:
                rejected[name] = f"{_FIELD_LABELS[name]} must be between {low} and {high}."
                return None
            return number

        for name in ("origin", "destination"):
            if changes.get(name) in (None, ""):
                continue
            airport = resolve_airport(str(changes[name]))
            if not airport:
                rejected[name] = f"Could not find an airport for '{changes[name]}'. Use a city name or a 3-letter IATA code."
                continue
            put(name, airport["code"])
            # If a city name was typed, keep that spelling ("Jessore") over the airport list's ("Jashahor").
            typed = str(changes[name]).strip()
            is_code = bool(re.fullmatch(r"[A-Za-z]{3}", typed) or re.search(r"\([A-Za-z]{3}\)", typed))
            typed_city = re.sub(r"\s*\(.*?\)", "", typed).split(",")[0].strip().title()
            put(f"{name}_city", airport["city"] if is_code or not typed_city else typed_city)
            if len(airport["alternatives"]) >= 2:
                others = ", ".join(f"{a['code']} ({a['name']})" for a in airport["alternatives"])
                notes.append(f"{airport['city']} has several airports; using {airport['code']}. Others: {others}.")
        if self.origin and self.origin == self.destination:
            notes.append("Origin and destination are the same airport - please check them.")

        for name in ("departure_date", "return_date"):
            if changes.get(name) in (None, ""):
                continue
            raw = str(changes[name]).strip()
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
                rejected[name] = f"{_FIELD_LABELS[name]} must look like YYYY-MM-DD."
                continue
            try:
                parsed = date.fromisoformat(raw)
            except ValueError:
                rejected[name] = f"'{raw}' is not a real date."
                continue
            if name == "departure_date" and parsed < today:
                rejected[name] = "Departure date cannot be in the past."
                continue
            put(name, raw)
        if self.departure_date and self.return_date and self.return_date <= self.departure_date:
            # Keep the previous dates: a return before departure would break every search.
            for name in ("departure_date", "return_date"):
                if name in changed:
                    setattr(self, name, changed.pop(name)["from"])
            rejected["return_date"] = "Return date must be later than the departure date. Dates were not changed."

        if "adults" in changes and changes["adults"] is not None:
            n = as_int("adults", 1, MAX_TRAVELLERS)
            if n is not None:
                put("adults", n)
        if "children" in changes and changes["children"] is not None:
            n = as_int("children", 0, MAX_TRAVELLERS - 1)
            if n is not None:
                put("children", n)
                if n == 0:
                    put("children_ages", [])
        if "rooms" in changes and changes["rooms"] is not None:
            n = as_int("rooms", 1, MAX_ROOMS)
            if n is not None:
                put("rooms", n)
        if self.adults + self.children > MAX_TRAVELLERS:
            rejected["adults"] = f"Adults + children cannot exceed {MAX_TRAVELLERS}. Travellers were not changed."
            for name in ("adults", "children"):
                if name in changed:
                    setattr(self, name, changed.pop(name)["from"])
        if self.rooms > self.adults:
            notes.append("More rooms than adults - hotel searches may fail; check the room count.")

        if changes.get("children_ages") is not None:
            ages = changes["children_ages"]
            if isinstance(ages, (int, float)) and not isinstance(ages, bool):
                ages = [ages]
            try:
                ages = [int(a) for a in ages]
                if any(a < 0 or a > 17 for a in ages):
                    raise ValueError
                put("children_ages", ages)
            except (TypeError, ValueError):
                rejected["children_ages"] = "Children's ages must be numbers between 0 and 17."
        if self.children and len(self.children_ages) != self.children:
            notes.append(f"No age given for every child; hotel searches will assume age {DEFAULT_CHILD_AGE} where unknown.")

        if changes.get("currency"):
            code = str(changes["currency"]).strip().upper()
            if re.fullmatch(r"[A-Z]{3}", code):
                put("currency", code)
            else:
                rejected["currency"] = "Currency must be a 3-letter code such as USD, EUR or BDT."

        if "budget" in changes and changes["budget"] is not None:
            try:
                amount = float(changes["budget"])
                if amount < 0:
                    raise ValueError
                put("budget", amount if amount > 0 else None)
            except (TypeError, ValueError):
                rejected["budget"] = "Budget must be a positive number."

        if "hotel_class" in changes and changes["hotel_class"] is not None:
            raw = changes["hotel_class"]
            stars = re.findall(r"[2-5]", ",".join(map(str, raw)) if isinstance(raw, (list, tuple)) else str(raw))
            put("hotel_class", ",".join(sorted(set(stars))))

        if "hotel_city" in changes and changes["hotel_city"] is not None:
            put("hotel_city", str(changes["hotel_city"]).strip())

        if "interests" in changes and changes["interests"] is not None:
            raw = changes["interests"]
            items = raw if isinstance(raw, (list, tuple)) else re.split(r"[,;]", str(raw))
            put("interests", [str(i).strip() for i in items if str(i).strip()][:5])

        if "stops" in changes and changes["stops"] is not None:
            n = as_int("stops", 0, 3)
            if n is not None:
                put("stops", n)

        return {"changed": changed, "rejected": rejected, "notes": notes}


def describe_changes(changed: Dict[str, Dict[str, Any]]) -> List[str]:
    """['Return: 2026-12-01 -> 2026-12-03', ...] for showing to people."""
    def show(v: Any) -> str:
        return "(none)" if v in ("", None, []) else (", ".join(map(str, v)) if isinstance(v, list) else str(v))
    return [f"{_FIELD_LABELS.get(k, k)}: {show(v['from'])} -> {show(v['to'])}" for k, v in changed.items()]
