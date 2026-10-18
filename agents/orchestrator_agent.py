from typing import Dict, Any, List, Optional
import asyncio
import json

from .base_agent import BaseAgent, LLMUnavailableError
from .flight_agent import FlightAgent
from .hotel_agent import HotelAgent
from .email_agent import EmailAgent
from utils.config import DEFAULT_CURRENCY, logger, redact
from utils.recommendations import (
    build_llm_prompt,
    parse_llm_recommendations,
    rule_based_recommendations,
)
from utils.validation import city_for_airport


class OrchestratorAgent(BaseAgent):
    def __init__(self):
        super().__init__(
            name="TravelOrchestrator",
            instructions="""Coordinate the complete travel planning workflow.
            Responsibilities:
            1. Manage flight searches for both outbound and return trips
            2. Handle hotel searches based on destination and dates
            3. Analyze and combine results for optimal travel suggestions
            4. Track workflow progress and handle any errors
            Consider: pricing optimization, scheduling efficiency, and user preferences.
            Provide comprehensive travel recommendations with detailed pricing and booking information.""",
        )
        self._setup_agents()

    def _setup_agents(self):
        """Initialize all specialized travel agents"""
        self.flight_agent = FlightAgent()
        self.hotel_agent = HotelAgent()
        self.email_agent = EmailAgent()

    async def run(self, messages: list) -> Dict[str, Any]:
        """Process a travel planning request.

        Differences from the original:
        * flights and hotels are searched at the same time;
        * if one of them fails the other is still returned (errors are listed);
        * NO email is sent here - emailing is a separate, explicit user action;
        * the AI step is optional and can never crash the search.
        """
        travel_request = self._load_payload(messages)
        if travel_request["return_date"] <= travel_request["departure_date"]:
            raise ValueError("Return date must be later than the departure date.")

        currency = travel_request.get("currency", DEFAULT_CURRENCY)
        flight_payload = {
            "origin": travel_request["origin"],
            "destination": travel_request["destination"],
            "departure_date": travel_request["departure_date"],
            "return_date": travel_request["return_date"],
            "adults": travel_request.get("adults", 1),
            "children": travel_request.get("children", 0),
            "stops": travel_request.get("stops", 1),
            "currency": currency,
        }
        hotel_payload = {
            "location": travel_request["destination"],
            "city": travel_request.get("city", ""),
            "check_in": travel_request["departure_date"],
            "check_out": travel_request["return_date"],
            "adults": travel_request.get("adults", 1),
            "children": travel_request.get("children", 0),
            "children_ages": travel_request.get("children_ages", []),
            "rooms": travel_request.get("rooms", 1),
            "sort_by": travel_request.get("sort_by", ""),
            "hotel_class": travel_request.get("hotel_class", ""),
            "currency": currency,
        }

        flights_outcome, hotels_outcome = await asyncio.gather(
            self._safe(self.flight_agent.run, flight_payload, "Flights"),
            self._safe(self.hotel_agent.run, hotel_payload, "Hotels"),
        )
        flights, flight_error = flights_outcome
        hotels, hotel_error = hotels_outcome
        errors = [e for e in (flight_error, hotel_error) if e]

        workflow_context: Dict[str, Any] = {
            "travel_request": travel_request,
            "flights": flights,
            "hotels": hotels,
            "errors": errors,
            "status": "failed" if flights is None and hotels is None else ("partial" if errors else "completed"),
        }
        if flights is None and hotels is None:
            raise RuntimeError("; ".join(errors) or "The search failed.")

        workflow_context["final_recommendations"] = await asyncio.to_thread(
            self._make_recommendations, flights, hotels
        )
        return workflow_context

    @staticmethod
    async def _safe(func, payload: Dict[str, Any], label: str):
        """Run one agent; return (result, None) or (None, friendly error message)."""
        try:
            return await func([{"role": "user", "content": json.dumps(payload)}]), None
        except Exception as exc:  # ProviderError, ValueError, unexpected bugs
            logger.warning("%s search failed: %s", label, redact(exc))
            return None, f"{label}: {redact(exc)}"

    def _make_recommendations(
        self, flights: Optional[Dict[str, Any]], hotels: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """AI recommendations when a model is configured and answers properly;
        otherwise a rule-based summary. Never raises."""
        fallback = rule_based_recommendations(flights, hotels)
        n_flights = len((flights or {}).get("recommended_flights") or [])
        n_hotels = len((hotels or {}).get("recommended_hotels") or [])
        if n_flights == 0 and n_hotels == 0:
            return fallback
        if not self.llm_configured:
            fallback["warnings"].append(
                "AI recommendations are not configured (LLM_BASE_URL / LLM_MODEL), so a rule-based summary is shown."
            )
            return fallback
        try:
            text = self._query_llm(build_llm_prompt(flights, hotels))
            parsed = self._parse_json_safely(text)
            result = parse_llm_recommendations(parsed, n_flights, n_hotels, self.llm_settings["model"] or "AI model")
            if result is None:
                fallback["warnings"].append("The AI model returned an unusable answer, so a rule-based summary is shown.")
                return fallback
            return result
        except LLMUnavailableError as exc:
            fallback["warnings"].append(f"AI recommendations unavailable ({exc}). A rule-based summary is shown.")
            return fallback
        except Exception as exc:  # last-resort guard: AI must never break the search
            logger.warning("Unexpected recommendation error: %s", redact(exc))
            fallback["warnings"].append("AI recommendations failed unexpectedly. A rule-based summary is shown.")
            return fallback
