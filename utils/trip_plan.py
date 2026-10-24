"""Day-by-day plan built ONLY from real search results (attractions + weather + picks).

Attractions are chosen by rating and number of reviews, then ordered so that
places close to each other share a day. The order is a simple nearest-neighbour
walk, not a route optimiser; opening hours are not checked.
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Any, Dict, List, Optional


def _score(a: Dict[str, Any]) -> float:
    rating = a.get("rating")
    if rating is None:
        return 0.0
    return rating * math.log10((a.get("reviews") or 0) + 10)


def _distance(a: Dict[str, Any], b: Dict[str, Any]) -> float:
    if None in (a.get("lat"), a.get("lon"), b.get("lat"), b.get("lon")):
        return 999.0
    return math.hypot(a["lat"] - b["lat"], (a["lon"] - b["lon"]) * math.cos(math.radians(a["lat"])))


def _walk(chosen: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not chosen:
        return []
    remaining = chosen[:]
    path = [remaining.pop(0)]
    while remaining:
        last = path[-1]
        nxt = min(remaining, key=lambda r: _distance(last, r))
        remaining.remove(nxt)
        path.append(nxt)
    return path


def build_trip_plan(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    req = report["request"]
    try:
        start, end = date.fromisoformat(req["departure_date"]), date.fromisoformat(req["return_date"])
    except (KeyError, ValueError, TypeError):
        return []
    n_days = (end - start).days + 1
    if n_days < 1:
        return []
    capacities = []
    for i in range(n_days):
        if n_days == 1:
            capacities.append(1)
        elif i == 0 or i == n_days - 1:
            capacities.append(1)   # travel days: keep light
        else:
            capacities.append(3)
    attractions = sorted((a for a in report.get("attractions", []) if a.get("rating") is not None), key=_score, reverse=True)
    chosen = _walk(attractions[: sum(capacities)])
    weather = {w["date"]: w for w in (report.get("weather") or {}).get("days", [])}

    days, cursor = [], 0
    for i, cap in enumerate(capacities):
        d = start + timedelta(days=i)
        label = "Arrival day" if i == 0 and n_days > 1 else ("Departure day" if i == n_days - 1 and n_days > 1 else f"Day {i + 1}")
        days.append({"day": i + 1, "date": d.isoformat(), "label": label, "weather": weather.get(d.isoformat()),
                     "attractions": chosen[cursor: cursor + cap]})
        cursor += cap
    return days
