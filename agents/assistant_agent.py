"""Follow-up questions and trip changes, with the current trip as context.

* With an AI model configured (LLM_BASE_URL / LLM_MODEL) the model answers from a compact
  JSON copy of the trip. It is told to use only that data.
* Without a model, simple rules answer the common questions from the same data.
* Requests to CHANGE the trip are never applied silently: they come back as a proposal
  (`changes`) that the user must confirm, because applying them runs a new paid search.
"""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from .base_agent import BaseAgent, LLMUnavailableError
from utils.config import logger, redact
from utils.report_data import fmt_money
from utils.validation import airport_info, airports_by_city

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
CHANGE_WORDS = re.compile(r"\b(change|update|make it|switch|move|extend|shorten|instead|reschedule|add|increase|reduce|modify)\b", re.I)
CURRENCY_RE = re.compile(r"\b([A-Z]{3})\b")


# ------------------------------------------------------------------ dates
def parse_dates(text: str, today: Optional[date] = None, near: Optional[date] = None) -> List[date]:
    """Dates found in text: 2026-12-05, 'Dec 5', '5th December'. Missing year = next occurrence."""
    today = today or date.today()
    found: List[tuple] = []
    for m in re.finditer(r"\b(\d{4})-(\d{2})-(\d{2})\b", text):
        try:
            found.append((m.start(), date(int(m.group(1)), int(m.group(2)), int(m.group(3)))))
        except ValueError:
            pass
    month_names = "|".join(MONTHS) + "|january|february|march|april|june|july|august|september|october|november|december"
    patterns = [
        (rf"\b({month_names})[a-z]*\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\b", lambda g: (g[0], g[1])),
        (rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({month_names})[a-z]*\b", lambda g: (g[1], g[0])),
    ]
    for pattern, order in patterns:
        for m in re.finditer(pattern, text, re.I):
            mon, day = order(m.groups())
            try:
                month = MONTHS[mon.lower()[:3]]
                d = date(near.year if near else today.year, month, int(day))
                if not near and d < today:
                    d = date(today.year + 1, month, int(day))
                found.append((m.start(), d))
            except (ValueError, KeyError):
                pass
    return [d for _, d in sorted(found, key=lambda t: t[0])]


# ------------------------------------------------------------ trip changes
def parse_trip_changes(text: str, request: Dict[str, Any], today: Optional[date] = None) -> Dict[str, Any]:
    """Turn 'extend by 2 days', 'return on Dec 10', '3 adults', 'to CDG' into proposed changes.

    Returns {"changes": {...}, "clarify": [str]}. `changes` uses the form's field names.
    """
    changes: Dict[str, Any] = {}
    clarify: List[str] = []
    low = text.lower()
    try:
        dep = date.fromisoformat(request["departure_date"])
        ret = date.fromisoformat(request["return_date"])
    except (KeyError, ValueError):
        dep = ret = None

    m = re.search(r"(\d+)\s*(?:adults?|people|persons|travell?ers|passengers)", low)
    if m and 1 <= int(m.group(1)) <= 9:
        changes["adults"] = int(m.group(1))
    m = re.search(r"(\d+)\s*(?:rooms?)", low)
    if m and 1 <= int(m.group(1)) <= 8:
        changes["rooms"] = int(m.group(1))
    m = re.search(r"(\d+)\s*(?:children|child|kids?)", low)
    if m:
        n = int(m.group(1))
        ages = [int(a) for a in re.findall(r"\b(\d{1,2})\b", low.split("aged")[-1])] if "aged" in low else []
        if n == 0:
            changes["children"], changes["children_ages"] = 0, []
        elif len(ages) == n and all(0 <= a <= 17 for a in ages):
            changes["children"], changes["children_ages"] = n, ages
        else:
            clarify.append(f"How old are the {n} child(ren)? (for example: \"{n} children aged 5 and 8\")")

    if dep and ret:
        m = re.search(r"(?:extend|add|stay)\D{0,25}?(\d+)\s*(?:more\s*)?(?:days?|nights?)", low)
        if m and re.search(r"extend|add|longer|more", low):
            changes["return_date"] = (ret + timedelta(days=int(m.group(1)))).isoformat()
        m = re.search(r"(?:shorten|cut|reduce)\D{0,25}?(\d+)\s*(?:days?|nights?)", low)
        if m and (ret - timedelta(days=int(m.group(1)))) > dep:
            changes["return_date"] = (ret - timedelta(days=int(m.group(1)))).isoformat()
        m = re.search(r"(?:for|stay)\s+(\d+)\s*nights?", low)
        if m and "return_date" not in changes:
            changes["return_date"] = (dep + timedelta(days=int(m.group(1)))).isoformat()

        dates = parse_dates(text, today, near=dep)
        if re.search(r"return|come back|back on|until|leave .*hotel|check.?out", low) and dates and not re.search(r"depart|leave on|fly out|check.?in", low):
            changes["return_date"] = dates[-1].isoformat()
        elif re.search(r"depart|leave on|fly out|check.?in|start", low) and dates and not re.search(r"return|come back|until|check.?out", low):
            changes["departure_date"] = dates[0].isoformat()
        elif len(dates) >= 2:
            changes["departure_date"], changes["return_date"] = dates[0].isoformat(), dates[1].isoformat()
        elif len(dates) == 1 and re.search(r"\bmove|shift|reschedule\b", low):
            shift = (dates[0] - dep).days
            changes["departure_date"] = dates[0].isoformat()
            changes["return_date"] = (ret + timedelta(days=shift)).isoformat()

    for key, pattern in (
        ("destination", r"(?:destination(?:\s+to)?|fly(?:ing)?\s+to|going\s+to|travel\s+to|switch\s+to|trip\s+to|instead(?:\s+of\s+\w+)?(?:\s+to)?)\s+([A-Za-z][A-Za-z .'-]{1,30})"),
        ("origin", r"(?:origin(?:\s+to)?|depart(?:ing)?\s+from|fly(?:ing)?\s+from|leaving\s+from|starting\s+from)\s+([A-Za-z][A-Za-z .'-]{1,30})"),
    ):
        m = re.search(pattern, text, re.I)
        if not m:
            continue
        place = re.split(r"\b(?:on|in|for|with|and|next|from|to|instead|please|then)\b|[,.;]", m.group(1).strip(), maxsplit=1)[0].strip()
        if not place or place.lower()[:3] in MONTHS and len(place.split()) <= 2 and re.search(r"\d", m.group(0) + text[m.end():m.end() + 3]):
            continue
        if re.fullmatch(r"[A-Za-z]{3}", place) and airport_info(place):
            changes[key] = place.upper()
        else:
            options = airports_by_city(place)
            if len(options) == 1:
                changes[key] = options[0]
            elif len(options) > 1:
                clarify.append(f"{place.title()} has several airports ({', '.join(options[:8])}). Which one do you want?")
    return {"changes": changes, "clarify": clarify}


# ----------------------------------------------------------------- context
def build_context(report: Dict[str, Any]) -> Dict[str, Any]:
    """Compact JSON copy of the trip that is safe to give to a model (no secrets, no email)."""
    def top(rows, keys, n=10):
        return [{k: r.get(k) for k in keys} for r in rows[:n]]

    ctx: Dict[str, Any] = {
        "request": report["request"],
        "flights": top(report["flights"], ["option", "airline", "flight_number", "departure", "arrival", "duration", "stops", "price", "currency"]),
        "hotels": top(report["hotels"], ["option", "name", "hotel_class", "rating", "reviews", "price_per_night", "total_price", "currency"]),
        "attractions": top(report.get("attractions", []), ["option", "name", "type", "rating", "reviews"]),
        "weather": [{k: d.get(k) for k in ("date", "mode", "summary", "tmax", "tmin", "rain_chance")} for d in (report.get("weather") or {}).get("days", [])],
        "recommendations": {k: report["recommendations"].get(k) for k in ("best_flight", "best_hotel", "summary")},
        "cost_estimate": report["cost_estimate"]["scenarios"],
        "budget": report.get("budget"),
    }
    return ctx


# ------------------------------------------------------------------- topics
TOPICS = {
    "flight": r"flight|fly|airline|plane|airfare|depart|arriv|layover|stop",
    "hotel": r"hotel|stay|room|accommodation|sleep|resort",
    "weather": r"weather|rain|temperature|cold|hot|warm|umbrella|pack|forecast|snow",
    "attractions": r"attraction|visit|see|sight|museum|park|things to do|tourist|activities|itinerary|plan",
    "cost": r"cost|price|budget|total|afford|how much|spend|pay",
    "currency": r"currency|convert|exchange|usd|eur|gbp|bdt|inr|rate",
}


def detect_topic(text: str, previous: Optional[str] = None) -> Optional[str]:
    low = text.lower()
    for topic, pattern in TOPICS.items():
        if re.search(pattern, low):
            return topic
    return previous  # follow-up like "and the cheapest?" keeps the earlier topic


class AssistantAgent(BaseAgent):
    def __init__(self):
        super().__init__(name="AssistantAgent", instructions="Answer follow-up questions about the planned trip using only the trip data provided.")

    # public entry point ------------------------------------------------
    def answer(self, question: str, report: Dict[str, Any], history: List[Dict[str, str]], rates: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Returns {"answer": str, "source": "ai"|"rules", "changes": dict, "clarify": [..]}."""
        proposal = {"changes": {}, "clarify": []}
        if CHANGE_WORDS.search(question) or re.search(r"\b\d+\s*(adults?|rooms?|nights?|days?)\b", question, re.I):
            proposal = parse_trip_changes(question, report["request"])
        previous_topic = None
        for turn in reversed(history):
            if turn["role"] == "user":
                previous_topic = detect_topic(turn["content"])
                if previous_topic:
                    break

        if self.llm_configured:
            try:
                text = self._ask_model(question, report, history)
                if text:
                    return {"answer": text, "source": "ai", **proposal}
            except LLMUnavailableError as exc:
                logger.info("Assistant model unavailable: %s", redact(exc))
            except Exception as exc:  # never let the chat crash the page
                logger.warning("Assistant error: %s", redact(exc))
        text = self._rules(question, report, detect_topic(question, previous_topic), rates)
        if proposal["changes"]:
            text = "I can update the trip with the changes below. Please confirm them to run a new search.\n\n" + text if False else "I understood this as a change request. Review the proposed changes below and confirm to run a new search."
        elif proposal["clarify"]:
            text = proposal["clarify"][0]
        return {"answer": text, "source": "rules", **proposal}

    # model ----------------------------------------------------------------
    def _ask_model(self, question: str, report: Dict[str, Any], history: List[Dict[str, str]]) -> str:
        system = (
            "You are a careful travel assistant. Answer ONLY from the TRIP JSON. Never invent prices, "
            "times, ratings, weather or places. If the data does not contain the answer, say so. "
            "Prices are search results, not bookings. Be concise. If the user wants to change the trip, "
            "tell them to confirm the proposed change; do not claim it has been applied."
        )
        turns = "\n".join(f"{t['role'].upper()}: {t['content']}" for t in history[-6:])
        prompt = f"TRIP: {json.dumps(build_context(report), ensure_ascii=False, default=str)}\n\nCONVERSATION SO FAR:\n{turns}\n\nUSER QUESTION: {question}"
        return self._query_llm(prompt, system=system).strip()

    # rules ----------------------------------------------------------------
    def _rules(self, question: str, report: Dict[str, Any], topic: Optional[str], rates: Optional[Dict[str, Any]]) -> str:
        cur = report["request"]["currency"]
        flights, hotels = report["flights"], report["hotels"]
        low = question.lower()
        req = report["request"]

        if topic == "flight":
            priced = [f for f in flights if f.get("price") is not None]
            if not flights:
                return "No flights were returned for this search."
            if re.search(r"fast|quick|short", low):
                timed = [f for f in flights if f.get("duration")]
                f = min(flights, key=lambda x: (x.get("duration_minutes") is None, x.get("duration_minutes") or 0))
                return f"The fastest option is #{f['option']} ({f.get('airline') or 'n/a'}), {f.get('duration') or 'n/a'}, {fmt_money(f.get('price'), cur)}."
            if priced:
                f = min(priced, key=lambda x: x["price"])
                nonstop = [x for x in priced if x.get("stops") == 0]
                extra = f" The cheapest nonstop is #{min(nonstop, key=lambda x: x['price'])['option']} at {fmt_money(min(nonstop, key=lambda x: x['price'])['price'], cur)}." if nonstop and nonstop[0] is not f else ""
                return f"The cheapest flight is #{f['option']} ({f.get('airline') or 'n/a'}) at {fmt_money(f['price'], cur)}, {f.get('duration') or 'duration n/a'}.{extra}"
            return f"{len(flights)} flights were found, but none has a price."
        if topic == "hotel":
            if not hotels:
                return "No hotels were returned for this search."
            if re.search(r"cheap|lowest|budget|afford", low):
                priced = [h for h in hotels if h.get("price_per_night") is not None]
                if priced:
                    h = min(priced, key=lambda x: x["price_per_night"])
                    return f"The cheapest hotel is #{h['option']} {h['name']} at {fmt_money(h['price_per_night'], cur)} per night."
            rated = [h for h in hotels if h.get("rating") is not None]
            if rated:
                h = max(rated, key=lambda x: (x["rating"], x.get("reviews") or 0))
                return f"The best-rated hotel is #{h['option']} {h['name']} ({h['rating']:.1f} stars, {fmt_money(h.get('price_per_night'), cur)} per night)."
            return f"{len(hotels)} hotels were found, but none has a rating."
        if topic == "weather":
            days = (report.get("weather") or {}).get("days") or []
            if not days:
                return "No weather data is available for this trip."
            hi = [d["tmax"] for d in days if d.get("tmax") is not None]
            lo = [d["tmin"] for d in days if d.get("tmin") is not None]
            wet = [d for d in days if (d.get("rain_chance") or 0) >= 50 or (d.get("precip") or 0) >= 1]
            kind = "typical conditions (average of recent years)" if report["weather"].get("has_typical") else "the forecast"
            parts = [f"Based on {kind}: highs around {max(hi):.0f}°C, lows around {min(lo):.0f}°C." if hi and lo else "Temperatures are not available."]
            parts.append(f"Rain is likely on {len(wet)} of {len(days)} days." + (" An umbrella is a good idea." if wet else ""))
            return " ".join(parts)
        if topic == "attractions":
            atts = report.get("attractions") or []
            if not atts:
                return "No attractions were returned for this destination."
            top = sorted([a for a in atts if a.get("rating") is not None], key=lambda a: (a["rating"], a.get("reviews") or 0), reverse=True)[:5]
            return "Top-rated attractions: " + "; ".join(f"{a['name']} ({a['rating']:.1f})" for a in top) + "."
        if topic in ("cost", "currency"):
            budget = report.get("budget")
            scen = (report["cost_estimate"]["scenarios"] or [None])[0]
            total = (budget or {}).get("total") if budget else (scen or {}).get("total")
            if total is None:
                return "There is not enough price data to calculate a total."
            text = f"The estimated total is {fmt_money(total, cur)}" + (" (flight + hotel only; open the Trip Cost tab to add food, transport and activities)." if not budget else ".")
            m = [c for c in CURRENCY_RE.findall(question) if c != cur]
            if m and rates:
                from .currency_agent import CurrencyAgent

                conv = CurrencyAgent.convert(total, cur, m[0], rates)
                if conv is not None:
                    text += f" That is about {fmt_money(conv, m[0])} at indicative rates."
            return text
        return (f"Your trip is {req['origin']} to {req['destination']}, {req['departure_date']} to {req['return_date']}. "
                "Ask me about flights, hotels, weather, attractions or the total cost, or say what you want to change "
                "(for example: \"extend the trip by 2 days\" or \"return on Dec 10\").")
