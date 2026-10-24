from typing import Any, Dict, Optional
import time

import requests

from .base_agent import BaseAgent
from utils.config import redact
from utils.serp_client import ProviderError

PRIMARY_URL = "https://open.er-api.com/v6/latest/{base}"       # free, no key, 160+ currencies incl. BDT
FALLBACK_URL = "https://api.frankfurter.app/latest?from={base}"  # ECB rates, ~30 currencies (no BDT)
CACHE_SECONDS = 6 * 3600
TIMEOUT = 10
COMMON_CURRENCIES = ["USD", "EUR", "GBP", "BDT", "INR", "AED", "SAR", "JPY", "CAD", "AUD", "SGD", "MYR", "CNY", "CHF", "THB", "TRY"]

_cache: Dict[str, Any] = {}


class CurrencyAgent(BaseAgent):
    """Currency conversion using free exchange-rate services. Rates are indicative, not bank rates."""

    def __init__(self):
        super().__init__(name="CurrencyAgent", instructions="Convert amounts between currencies.")

    async def run(self, messages: list) -> Dict[str, Any]:
        payload = self._load_payload(messages)
        rates = self.get_rates(payload.get("base", "USD"))
        if payload.get("amount") is not None and payload.get("to"):
            rates["converted"] = self.convert(float(payload["amount"]), rates["base"], payload["to"], rates)
        return rates

    def get_rates(self, base: str = "USD") -> Dict[str, Any]:
        base = base.upper()
        hit = _cache.get(base)
        if hit and time.time() - hit["fetched"] < CACHE_SECONDS:
            return hit["data"]
        errors = []
        for url, parse in ((PRIMARY_URL, self._parse_er), (FALLBACK_URL, self._parse_frankfurter)):
            try:
                response = requests.get(url.format(base=base), timeout=TIMEOUT)
                response.raise_for_status()
                data = parse(response.json(), base)
                if data["rates"]:
                    _cache[base] = {"fetched": time.time(), "data": data}
                    return data
            except (requests.exceptions.RequestException, ValueError, KeyError) as exc:
                errors.append(type(exc).__name__)
        raise ProviderError(f"Exchange rates are unavailable right now ({', '.join(redact(e) for e in errors)}).")

    @staticmethod
    def _parse_er(payload: Dict[str, Any], base: str) -> Dict[str, Any]:
        if payload.get("result") != "success":
            raise ValueError("rate service error")
        return {
            "base": base, "rates": {k: float(v) for k, v in (payload.get("rates") or {}).items()},
            "updated": payload.get("time_last_update_utc"), "source": "ExchangeRate-API (open.er-api.com)",
        }

    @staticmethod
    def _parse_frankfurter(payload: Dict[str, Any], base: str) -> Dict[str, Any]:
        rates = {k: float(v) for k, v in (payload.get("rates") or {}).items()}
        rates[base] = 1.0
        return {"base": base, "rates": rates, "updated": payload.get("date"), "source": "Frankfurter (ECB reference rates)"}

    @staticmethod
    def convert(amount: Optional[float], from_cur: str, to_cur: str, rates: Dict[str, Any]) -> Optional[float]:
        """Convert using a rates table whose base may differ from `from_cur`. None if a rate is missing."""
        if amount is None:
            return None
        table = rates.get("rates") or {}
        from_cur, to_cur = from_cur.upper(), to_cur.upper()
        if from_cur == to_cur:
            return amount
        base = rates.get("base", "USD").upper()
        try:
            in_base = amount if from_cur == base else amount / table[from_cur]
            return in_base if to_cur == base else in_base * table[to_cur]
        except (KeyError, ZeroDivisionError):
            return None
