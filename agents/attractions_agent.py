from typing import Any, Dict, List, Optional
from datetime import datetime
from urllib.parse import quote

from .base_agent import BaseAgent
from utils.serp_client import NoResultsError, serpapi_search

MAX_ATTRACTIONS = 20


def _num(value: Any) -> Optional[float]:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def maps_link(title: str, place_id: Optional[str], lat: Optional[float], lon: Optional[float]) -> Optional[str]:
    """Official Google Maps URL for a place (opens in Google Maps; no API key needed)."""
    if place_id:
        return f"https://www.google.com/maps/search/?api=1&query={quote(title)}&query_place_id={quote(str(place_id))}"
    if lat is not None and lon is not None:
        return f"https://www.google.com/maps/search/?api=1&query={lat},{lon}"
    return None


class AttractionsAgent(BaseAgent):
    """Finds tourist attractions for the destination (SerpAPI - Google Maps)."""

    def __init__(self):
        super().__init__(
            name="AttractionsAgent",
            instructions="Find well-rated tourist attractions and sights at the destination.",
        )

    async def run(self, messages: list) -> Dict[str, Any]:
        params = self._load_payload(messages)
        return self._parse(self.search(params))

    def search(self, params: Dict[str, Any]) -> Dict[str, Any]:
        city = (params.get("city") or "").strip()
        query = {"engine": "google_maps", "type": "search", "hl": "en", "q": f"tourist attractions in {city}"}
        lat, lon = params.get("lat"), params.get("lon")
        if lat is not None and lon is not None:
            query["ll"] = f"@{lat},{lon},12z"
        try:
            return serpapi_search(query)
        except NoResultsError:
            return {}

    def _parse(self, data: Dict[str, Any]) -> Dict[str, Any]:
        rows: List[Dict[str, Any]] = []
        for item in (data or {}).get("local_results") or []:
            if not isinstance(item, dict) or not item.get("title"):
                continue
            gps = item.get("gps_coordinates") or {}
            lat, lon = _num(gps.get("latitude")), _num(gps.get("longitude"))
            types = item.get("types") if isinstance(item.get("types"), list) else []
            title = str(item["title"])
            rows.append(
                {
                    "name": title,
                    "type": item.get("type") or (types[0] if types else None),
                    "rating": _num(item.get("rating")),
                    "reviews": item.get("reviews") if isinstance(item.get("reviews"), int) else None,
                    "address": item.get("address"),
                    "description": item.get("description"),
                    "thumbnail": item.get("thumbnail"),
                    "lat": lat,
                    "lon": lon,
                    "map_url": maps_link(title, item.get("place_id"), lat, lon),
                }
            )
            if len(rows) >= MAX_ATTRACTIONS:
                break
        return {
            "attractions": rows,
            "number_of_options": len(rows),
            "search_timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "source": "SerpAPI - Google Maps",
        }
