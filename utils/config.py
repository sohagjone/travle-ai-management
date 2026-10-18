"""Configuration helpers: read secrets safely and never leak them.

Secrets can come from (in this order):
1. Environment variables (also what a local `.env` file becomes via python-dotenv)
2. Streamlit secrets (`.streamlit/secrets.toml` locally, or the "Secrets" box on Streamlit Cloud)
"""

from __future__ import annotations

import logging
import os
import re
from typing import Optional

DEFAULT_CURRENCY = "USD"

# Names of every secret/config value the app can use.
SECRET_NAMES = (
    "SERPAPI_API_KEY",
    "SENDGRID_KEY",
    "SENDGRID_FROM_EMAIL",
    "LLM_API_KEY",
    "LLM_BASE_URL",
    "LLM_MODEL",
)

logger = logging.getLogger("travel_app")


def get_secret(name: str, default: Optional[str] = None) -> Optional[str]:
    """Return a configuration value from the environment or Streamlit secrets."""
    value = os.getenv(name)
    if value:
        return value.strip()
    try:
        import streamlit as st

        if name in st.secrets:
            secret_value = st.secrets[name]
            if secret_value:
                return str(secret_value).strip()
    except Exception:
        # No secrets file, or not running inside Streamlit: that's fine.
        pass
    return default


_API_KEY_PATTERN = re.compile(r"(api[_-]?key=)[^&\s'\"]+", re.IGNORECASE)
_BEARER_PATTERN = re.compile(r"(Bearer\s+)[A-Za-z0-9._\-]+", re.IGNORECASE)


def redact(text: object) -> str:
    """Remove API keys from any text before it is logged or shown to a user.

    Handles `api_key=...` query strings (which appear inside requests' error
    messages), bearer tokens, and the literal value of every known secret.
    """
    cleaned = str(text)
    cleaned = _API_KEY_PATTERN.sub(r"\1***", cleaned)
    cleaned = _BEARER_PATTERN.sub(r"\1***", cleaned)
    for name in SECRET_NAMES:
        if name in ("SENDGRID_FROM_EMAIL", "LLM_BASE_URL", "LLM_MODEL"):
            continue  # not secret
        secret = get_secret(name)
        if secret and len(secret) >= 6:
            cleaned = cleaned.replace(secret, "***")
    return cleaned
