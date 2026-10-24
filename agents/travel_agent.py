"""The AI travel agent, and - for comparison - a traditional chatbot.

AGENT  = an AI model that can call tools in a loop:  think -> call tool(s) -> read the results -> think again
         ... -> answer.  It keeps a structured trip memory (TripState) next to the chat history.
CHATBOT = the same AI model with NO tools: it can only answer from what it learned in training,
         so it cannot know today's prices, the weather next week or live exchange rates.

Both use any OpenAI-compatible endpoint (LLM_BASE_URL / LLM_MODEL / LLM_API_KEY), like the rest of the app.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional

from utils.config import logger, redact
from utils.travel_tools import ToolCall, TravelTools, shrink

from .base_agent import BaseAgent, LLMUnavailableError

MAX_TOOL_ROUNDS = 8          # safety limit: at most 8 think -> act rounds per question
MAX_HISTORY_MESSAGES = 40    # older turns are dropped (the TripState still remembers the trip)
MAX_PARALLEL_TOOLS = 5

AGENT_INSTRUCTIONS = """You are a careful AI travel-planning agent. You help people plan trips by using tools to get REAL data.

How to work:
1. Keep the shared trip memory up to date. When the person gives or changes any requirement (cities, dates, travellers, budget,
   hotel stars, interests, currency), call update_trip_details FIRST with only what changed. Never ask again for something that is
   already in the trip memory below.
2. If something essential is missing (departure city, destination, dates), ask ONE short question instead of guessing.
   Resolve relative dates ("next Friday", "for a week") using today's date and tell the person the exact dates you used.
3. Use tools for facts: flights and hotels for prices, find_attractions for things to do, get_weather for the weather,
   web_search for visas / events / anything else, convert_currency for exchange rates, calculate_trip_cost for totals.
   Call independent tools together in one step (for example flights, hotels and weather).
4. NEVER invent prices, ratings, flights, weather or exchange rates, and never do currency or cost arithmetic yourself - use the tools.
5. After a change, search again ONLY the results marked STALE below; reuse everything marked "up to date".
6. If a tool returns an error, read it: fix the input, ask the person, or explain the problem honestly. Do not pretend it worked.
7. Be clear about limits: prices are search results, not bookings; a weather result with mode "typical_from_last_year" is not a forecast.
8. Answer concisely with the key numbers, include links the tools gave you, and end with the most useful next step or question.
"""

CHATBOT_INSTRUCTIONS = """You are a travel assistant chatbot. You have NO tools and NO internet access: you can only answer from your
general knowledge. If asked for live information (current prices, availability, forecasts, exchange rates) say honestly what you
cannot know, and give general guidance instead. Keep answers concise."""


@dataclass
class AgentTurn:
    reply: str
    calls: List[ToolCall] = field(default_factory=list)
    rounds: int = 0
    error: Optional[str] = None


class _LLMMixin(BaseAgent):
    """Shared LLM access (the base class already knows how to read the LLM_* settings)."""

    def __init__(self, name: str, client: Any = None, model: Optional[str] = None):
        super().__init__(name=name, instructions="")
        if client is not None:
            self._llm_client = client
        self._model_override = model

    @property
    def available(self) -> bool:
        return self._llm_client is not None or self.llm_configured

    @property
    def model_name(self) -> str:
        return self._model_override or self.llm_settings["model"] or "model"

    def _create(self, **kwargs: Any) -> Any:
        client = self._get_llm_client()
        try:
            return client.chat.completions.create(model=self.model_name, **kwargs)
        except LLMUnavailableError:
            raise
        except Exception as exc:  # network, bad key, model without tool support...
            logger.warning("LLM request failed: %s", redact(exc))
            hint = " (does this model support tool calling?)" if "tool" in str(exc).lower() else ""
            raise LLMUnavailableError(f"The AI model could not answer: {redact(exc)}{hint}") from None


class TravelAgent(_LLMMixin):
    def __init__(self, tools: Optional[TravelTools] = None, client: Any = None, model: Optional[str] = None,
                 today: Optional[date] = None):
        super().__init__("TravelAgent", client, model)
        self.tools = tools or TravelTools()
        self.history: List[Dict[str, Any]] = []
        self.today = today

    # ---------------------------------------------------------- context
    def system_prompt(self) -> str:
        """Rebuilt every turn, so the model always sees the CURRENT trip and which results are stale."""
        today = self.today or date.today()
        return (
            f"{AGENT_INSTRUCTIONS}\n"
            f"Today's date: {today.isoformat()} ({today.strftime('%A')}).\n\n"
            f"TRIP MEMORY (current):\n{self.tools.state.summary()}\n\n"
            "RESULTS ON FILE:\n" + "\n".join(self.tools.status_lines())
        )

    def reset(self) -> None:
        self.history.clear()
        self.tools.reset()

    def _trim_history(self) -> None:
        """Drop the oldest turns, always cutting at a user message so tool replies are never orphaned."""
        if len(self.history) <= MAX_HISTORY_MESSAGES:
            return
        start = len(self.history) - MAX_HISTORY_MESSAGES
        while start < len(self.history) and self.history[start]["role"] != "user":
            start += 1
        self.history = self.history[start:] if start < len(self.history) else self.history[-2:]

    # ---------------------------------------------------------- the loop
    def chat(self, user_message: str) -> AgentTurn:
        """Answer one message. May call several tools over several rounds before replying."""
        text = (user_message or "").strip()
        if not text:
            return AgentTurn(reply="", error="Please type a message.")
        if not self.available:
            return AgentTurn(reply="", error="No AI model is configured (set LLM_BASE_URL and LLM_MODEL), so the chat agent is unavailable.")

        self.history.append({"role": "user", "content": text})
        self._trim_history()
        calls_before = len(self.tools.trace)
        rounds = 0
        try:
            while rounds < MAX_TOOL_ROUNDS:
                rounds += 1
                response = self._create(
                    messages=[{"role": "system", "content": self.system_prompt()}] + self.history,
                    tools=self.tools.specs(), tool_choice="auto", temperature=0.2, max_tokens=1500,
                )
                message = response.choices[0].message
                tool_calls = list(getattr(message, "tool_calls", None) or [])
                entry: Dict[str, Any] = {"role": "assistant", "content": message.content or ""}
                if tool_calls:
                    entry["tool_calls"] = [
                        {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments or "{}"}}
                        for tc in tool_calls
                    ]
                self.history.append(entry)
                if not tool_calls:
                    return AgentTurn(message.content or "", self.tools.trace[calls_before:], rounds)
                for tc, result in zip(tool_calls, self._run_tool_calls(tool_calls)):
                    self.history.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(shrink(result), default=str, ensure_ascii=False)})

            # Too many rounds: stop calling tools and ask for the best answer from what we have.
            final = self._create(
                messages=[{"role": "system", "content": self.system_prompt() + "\nYou have used all tool rounds. Answer now with what you have and say what is missing."}] + self.history,
                temperature=0.2, max_tokens=1200,
            )
            reply = final.choices[0].message.content or ""
            self.history.append({"role": "assistant", "content": reply})
            return AgentTurn(reply, self.tools.trace[calls_before:], rounds)
        except LLMUnavailableError as exc:
            self._drop_unfinished_turn()
            return AgentTurn(reply="", calls=self.tools.trace[calls_before:], rounds=rounds, error=str(exc))

    def _run_tool_calls(self, tool_calls: List[Any]) -> List[Dict[str, Any]]:
        parsed = []
        for tc in tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
                args = args if isinstance(args, dict) else {}
            except (json.JSONDecodeError, TypeError):
                args = None
            parsed.append((tc.function.name, args))

        def run(item):
            name, args = item
            if args is None:
                return {"error": f"The arguments for {name} were not valid JSON. Call it again with a valid JSON object."}
            return self.tools.call(name, args, source="agent")

        # Order matters when the trip is being changed, so run those one by one; pure searches can run together.
        if len(parsed) == 1 or any(name == "update_trip_details" for name, _ in parsed):
            return [run(item) for item in parsed]
        with ThreadPoolExecutor(max_workers=min(MAX_PARALLEL_TOOLS, len(parsed))) as pool:
            return list(pool.map(run, parsed))

    def _drop_unfinished_turn(self) -> None:
        """After a model failure, remove the dangling part of this turn so the next message starts clean."""
        while self.history and self.history[-1]["role"] != "user":
            self.history.pop()
        if self.history:
            self.history.pop()


class TraditionalChatbot(_LLMMixin):
    """Same model, no tools, no trip memory: the baseline the agent is compared against."""

    def __init__(self, client: Any = None, model: Optional[str] = None):
        super().__init__("TraditionalChatbot", client, model)

    def reply(self, user_message: str) -> str:
        if not self.available:
            raise LLMUnavailableError("No AI model is configured (set LLM_BASE_URL and LLM_MODEL).")
        response = self._create(
            messages=[{"role": "system", "content": CHATBOT_INSTRUCTIONS}, {"role": "user", "content": user_message}],
            temperature=0.2, max_tokens=900,
        )
        return response.choices[0].message.content or ""
