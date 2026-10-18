from typing import Dict, Any, Optional
import json
from datetime import datetime

from utils.config import get_secret, logger, redact

CURRENT_YEAR = datetime.now().year

EMAILS_SYSTEM_PROMPT = """Your task is to convert structured markdown-like text into a valid HTML email body.

- Do not include a ```html preamble in your response.
- The output should be in proper HTML format, ready to be used as the body of an email.
Here is an example:
<example>
Input:

I want to travel to New York from Madrid from October 1-7. Find me flights and 4-star hotels.

Expected Output:

<!DOCTYPE html>
<html>
<head>
    <title>Flight and Hotel Options</title>
</head>
<body>
    <h2>Flights from Madrid to New York</h2>
    <ol>
        <li>
            <strong>American Airlines</strong><br>
            <strong>Departure:</strong> Adolfo Suárez Madrid–Barajas Airport (MAD) at 10:25 AM<br>
            <strong>Arrival:</strong> John F. Kennedy International Airport (JFK) at 12:25 PM<br>
            <strong>Duration:</strong> 8 hours<br>
            <strong>Aircraft:</strong> Boeing 777<br>
            <strong>Class:</strong> Economy<br>
            <strong>Price:</strong> $702<br>
            <img src="https://www.gstatic.com/flights/airline_logos/70px/AA.png" alt="American Airlines"><br>
            <a href="https://www.google.com/flights">Book on Google Flights</a>
        </li>
        <li>
            <strong>Iberia</strong><br>
            <strong>Departure:</strong> Adolfo Suárez Madrid–Barajas Airport (MAD) at 12:25 PM<br>
            <strong>Arrival:</strong> John F. Kennedy International Airport (JFK) at 2:40 PM<br>
            <strong>Duration:</strong> 8 hours 15 minutes<br>
            <strong>Aircraft:</strong> Airbus A330<br>
            <strong>Class:</strong> Economy<br>
            <strong>Price:</strong> $702<br>
            <img src="https://www.gstatic.com/flights/airline_logos/70px/IB.png" alt="Iberia"><br>
            <a href="https://www.google.com/flights">Book on Google Flights</a>
        </li>
        <li>
            <strong>Delta Airlines</strong><br>
            <strong>Departure:</strong> Adolfo Suárez Madrid–Barajas Airport (MAD) at 10:00 AM<br>
            <strong>Arrival:</strong> John F. Kennedy International Airport (JFK) at 12:30 PM<br>
            <strong>Duration:</strong> 8 hours 30 minutes<br>
            <strong>Aircraft:</strong> Boeing 767<br>
            <strong>Class:</strong> Economy<br>
            <strong>Price:</strong> $738<br>
            <img src="https://www.gstatic.com/flights/airline_logos/70px/DL.png" alt="Delta Airlines"><br>
            <a href="https://www.google.com/flights">Book on Google Flights</a>
        </li>
    </ol>

    <h2>4-Star Hotels in New York</h2>
    <ol>
        <li>
            <strong>NobleDen Hotel</strong><br>
            <strong>Description:</strong> Modern, polished hotel offering sleek rooms, some with city-view balconies, plus free Wi-Fi.<br>
            <strong>Location:</strong> Near Washington Square Park, Grand St, and JFK Airport.<br>
            <strong>Rate per Night:</strong> $537<br>
            <strong>Total Rate:</strong> $3,223<br>
            <strong>Rating:</strong> 4.8/5 (656 reviews)<br>
            <strong>Amenities:</strong> Free Wi-Fi, Parking, Air conditioning, Restaurant, Accessible, Business centre, Child-friendly, Smoke-free property<br>
            <img src="https://lh5.googleusercontent.com/p/AF1QipNDUrPJwBhc9ysDhc8LA822H1ZzapAVa-WDJ2d6=s287-w287-h192-n-k-no-v1" alt="NobleDen Hotel"><br>
            <a href="http://www.nobleden.com/">Visit Website</a>
        </li>
    </ol>
</body>
</html>

</example>
"""

TOOLS_SYSTEM_PROMPT = f"""You are a smart travel agency. Use the tools to look up information.
    You are allowed to make multiple calls (either together or in sequence).
    Only look up information when you are sure of what you want.
    The current year is {CURRENT_YEAR}.
    If you need to look up some information before asking a follow up question, you are allowed to do that!
    I want to have in your output links to hotels websites and flights websites (if possible).
    I want to have as well the logo of the hotel and the logo of the airline company (if possible).
    In your output always include the price of the flight and the price of the hotel and the currency as well (if possible).
    for example for hotels-
    Rate: $581 per night
    Total: $3,488
"""


class LLMUnavailableError(Exception):
    """The AI model is not configured or could not be reached."""


class BaseAgent:
    """Shared behaviour for all agents.

    The AI model is OPTIONAL. It is configured with three settings (environment
    variables or Streamlit secrets):

        LLM_BASE_URL  OpenAI-compatible endpoint, e.g. https://api.openai.com/v1
                      (for local development with Ollama: http://localhost:11434/v1)
        LLM_API_KEY   key for that endpoint (Ollama accepts any text, e.g. "ollama")
        LLM_MODEL     model name, e.g. gpt-4o-mini  (Ollama: llama3.2)

    If these are not set, the app still works: flights, hotels and downloads do
    not need an AI model. A deterministic summary is used instead.
    """

    def __init__(self, name: str, instructions: str, agent_type: str = "tools"):
        self.name = name
        self.instructions = (
            TOOLS_SYSTEM_PROMPT if agent_type == "tools" else EMAILS_SYSTEM_PROMPT
        )
        self._llm_client = None

    # ------------------------------------------------------------------ LLM
    @property
    def llm_settings(self) -> Dict[str, Optional[str]]:
        return {
            "base_url": get_secret("LLM_BASE_URL"),
            "api_key": get_secret("LLM_API_KEY"),
            "model": get_secret("LLM_MODEL"),
        }

    @property
    def llm_configured(self) -> bool:
        s = self.llm_settings
        return bool(s["base_url"] and s["model"])

    def _get_llm_client(self):
        if self._llm_client is None:
            if not self.llm_configured:
                raise LLMUnavailableError(
                    "No AI model configured (set LLM_BASE_URL and LLM_MODEL)."
                )
            from openai import OpenAI  # imported lazily so the app starts without it

            s = self.llm_settings
            self._llm_client = OpenAI(
                base_url=s["base_url"],
                api_key=s["api_key"] or "not-needed",
                timeout=45.0,
                max_retries=1,
            )
        return self._llm_client

    async def run(self, messages: list) -> Dict[str, Any]:
        """Default run method to be overridden by child classes"""
        raise NotImplementedError("Subclasses must implement run()")

    def _query_llm(self, prompt: str, system: Optional[str] = None) -> str:
        """Ask the configured OpenAI-compatible model. Raises LLMUnavailableError."""
        client = self._get_llm_client()
        try:
            response = client.chat.completions.create(
                model=self.llm_settings["model"],
                messages=[
                    {"role": "system", "content": system or self.instructions},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                max_tokens=2000,
            )
            return response.choices[0].message.content or ""
        except LLMUnavailableError:
            raise
        except Exception as exc:  # network errors, bad key, bad model name...
            logger.warning("LLM request failed: %s", redact(exc))
            raise LLMUnavailableError(f"The AI model could not be reached: {redact(exc)}") from None

    # Backwards-compatible name used by the original code.
    _query_ollama = _query_llm

    @staticmethod
    def _load_payload(messages: list) -> Dict[str, Any]:
        """Read the JSON payload from the last message (replaces the old eval())."""
        content = messages[-1]["content"]
        if isinstance(content, dict):
            return content
        payload = json.loads(content)
        if not isinstance(payload, dict):
            raise ValueError("Agent payload must be a JSON object.")
        return payload

    def _parse_json_safely(self, text: str) -> Dict[str, Any]:
        """Safely parse JSON from text, handling potential errors"""
        try:
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1:
                parsed = json.loads(text[start : end + 1])
                if isinstance(parsed, dict):
                    return parsed
                return {"error": "JSON content was not an object"}
            return {"error": "No JSON content found"}
        except (json.JSONDecodeError, TypeError, AttributeError):
            return {"error": "Invalid JSON content"}
