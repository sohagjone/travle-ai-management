from typing import Dict, Any, List, Optional
from datetime import datetime

from .base_agent import BaseAgent
from utils.config import DEFAULT_CURRENCY
from utils.serp_client import serpapi_search, NoResultsError
from utils.validation import city_for_airport


def _to_number(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


class CityResolverAgent(BaseAgent):
    """Turns an airport code (e.g. AMS) into a city name (Amsterdam).

    The original version asked a local Ollama model, which cannot work on
    Streamlit Cloud and could answer with a whole sentence. This version uses
    an offline airport list (the `airportsdata` package) instead.
    """

    def __init__(self):
        super().__init__(
            name="CityResolverAgent",
            instructions="Identifies cities based on airport codes using an offline airport list.",
        )

    def get_city_from_airport_code(self, airport_code: str) -> Optional[str]:
        return city_for_airport(airport_code)


class HotelAgent(BaseAgent):
    def __init__(self):
        super().__init__(
            name="HotelAgent",
            instructions="""Search and analyze hotel options.
            Consider: price, location, amenities, and guest ratings.
            Provide detailed hotel information with images and booking links.
            Return results in HTML format with pricing, amenities, and location details.""",
        )
        self.city_resolver_agent = CityResolverAgent()

    async def run(self, messages: list) -> Dict[str, Any]:
        """Search hotels and return parsed, structured results."""
        search_params = self._load_payload(messages)

        # Prefer an explicit city typed by the user; otherwise resolve the airport code.
        city = (search_params.get("city") or "").strip()
        if not city:
            code = search_params.get("location", "")
            city = self.city_resolver_agent.get_city_from_airport_code(code) or ""
        if not city:
            raise ValueError(
                f"Could not work out which city to search for hotels from '{search_params.get('location')}'. "
                "Please type the hotel city in the form."
            )
        search_params["location"] = city

        data = self.search_hotels(search_params)
        result = self._parse_hotel_data(data, currency=search_params.get("currency", DEFAULT_CURRENCY))
        result["search_city"] = city
        return result

    def search_hotels(self, params: Dict[str, Any]) -> Dict[str, Any]:
        children = int(params.get("children", 0) or 0)
        children_ages = params.get("children_ages") or []
        search_params = {
            "engine": "google_hotels",
            "hl": "en",
            "gl": "us",
            # The original code was missing the space after "hotels in".
            "q": "hotels in " + params.get("location", ""),
            "check_in_date": params.get("check_in", ""),
            "check_out_date": params.get("check_out", ""),
            "currency": params.get("currency", DEFAULT_CURRENCY),
            "adults": params.get("adults", 1),
            "children": children,
            "children_ages": ",".join(str(a) for a in children_ages) if children else "",
            "rooms": params.get("rooms", 1),
            "sort_by": params.get("sort_by", ""),
            "hotel_class": params.get("hotel_class", ""),
        }
        try:
            return serpapi_search(search_params)
        except NoResultsError:
            return {}  # "0 hotels", not a failure

    def _parse_hotel_data(self, data: Dict[str, Any], currency: str = DEFAULT_CURRENCY) -> Dict[str, Any]:
        """Parse hotel data from the API response (missing fields stay None/empty)."""
        if not isinstance(data, dict):
            data = {}
        hotels: List[Dict[str, Any]] = []
        for prop in data.get("properties") or []:
            if not isinstance(prop, dict) or not prop.get("name"):
                continue
            rate = prop.get("rate_per_night") or {}
            total = prop.get("total_rate") or {}
            images = prop.get("images") or []
            first_image = images[0] if images and isinstance(images[0], dict) else {}
            amenities = prop.get("amenities")
            hotels.append(
                {
                    "name": prop.get("name"),
                    "type": prop.get("type"),
                    "rating": _to_number(prop.get("overall_rating")),
                    "reviews": prop.get("reviews"),
                    "hotel_class": prop.get("hotel_class"),
                    "price_per_night": rate.get("lowest"),
                    "price_per_night_value": _to_number(rate.get("extracted_lowest")),
                    "total_price": total.get("lowest"),
                    "total_price_value": _to_number(total.get("extracted_lowest")),
                    "currency": currency,
                    "description": prop.get("description"),
                    "amenities": [str(a) for a in amenities] if isinstance(amenities, list) else [],
                    "image_url": first_image.get("thumbnail"),
                    "booking_url": prop.get("link"),
                }
            )
        return {
            "recommended_hotels": hotels,
            "search_timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "number_of_options": len(hotels),
            "source": "SerpAPI - Google Hotels",
        }
