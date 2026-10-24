"""The complete travel-planning WORKFLOW, with no AI model needed.

A workflow runs a fixed recipe:   flights + hotels + weather + attractions + tips  (in parallel)
                                  -> cost calculation -> optional currency conversion.
An agent (agents/travel_agent.py) decides the steps itself. Both use the SAME tools, so the
difference is only "who chooses the next step".

`plan()` is also how the workflow reacts when requirements change: it re-runs ONLY the searches
whose inputs changed and reuses the rest.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from utils.travel_tools import TravelTools

# tool name used for the search, per result key
_STEP_TOOL = {"flights": "search_flights", "hotels": "search_hotels", "weather": "get_weather",
              "attractions": "find_attractions", "tips": "search_tips"}
STEP_LABELS = {"flights": "Flights", "hotels": "Hotels", "weather": "Weather", "attractions": "Attractions", "tips": "Travel tips (web search)"}


@dataclass
class PlanRun:
    ran: List[str] = field(default_factory=list)
    reused: List[str] = field(default_factory=list)
    skipped: Dict[str, str] = field(default_factory=dict)   # step -> reason (missing details)
    errors: Dict[str, str] = field(default_factory=dict)    # step -> error message
    cost: Optional[Dict[str, Any]] = None
    seconds: float = 0.0


class TripPlanner:
    def __init__(self, tools: TravelTools):
        self.tools = tools

    def plan(
        self,
        include_tips: bool = True,
        convert_total_to: str = "",
        food_per_person_per_day: float = 0,
        activities_per_person_per_day: float = 0,
        local_transport_per_day: float = 0,
        force: bool = False,
        flight_option: Optional[int] = None,
        hotel_option: Optional[int] = None,
    ) -> PlanRun:
        started = time.time()
        run = PlanRun()
        steps = ["flights", "hotels", "weather", "attractions"] + (["tips"] if include_tips else [])

        to_run: List[str] = []
        for step in steps:
            missing = self.tools.state.missing_for(step)
            if missing:
                run.skipped[step] = "missing " + ", ".join(missing)
            elif not force and not self.tools.is_stale(step):
                run.reused.append(step)
            else:
                to_run.append(step)

        def execute(step: str) -> Dict[str, Any]:
            if force:  # force a refresh by dropping the stored result first
                self.tools.results.pop(step, None)
            return self.tools.call(_STEP_TOOL[step], {}, source="workflow")

        if to_run:
            with ThreadPoolExecutor(max_workers=len(to_run)) as pool:
                outcomes = list(pool.map(execute, to_run))
            for step, outcome in zip(to_run, outcomes):
                if "error" in outcome:
                    run.errors[step] = str(outcome["error"])
                else:
                    run.ran.append(step)

        if self.tools.data("flights") is not None or self.tools.data("hotels") is not None:
            cost = self.tools.call("calculate_trip_cost", {
                "food_per_person_per_day": food_per_person_per_day,
                "activities_per_person_per_day": activities_per_person_per_day,
                "local_transport_per_day": local_transport_per_day,
                "convert_to": convert_total_to,
                "flight_option": flight_option,
                "hotel_option": hotel_option,
            }, source="workflow")
            run.cost = None if "error" in cost else cost
            if "error" in cost:
                run.errors["cost"] = str(cost["error"])
        run.seconds = round(time.time() - started, 1)
        return run
