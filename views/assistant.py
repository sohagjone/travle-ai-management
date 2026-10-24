"""Assistant tab: context-aware follow-up questions and confirmed trip updates."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

import streamlit as st

from agents.assistant_agent import AssistantAgent
from agents.currency_agent import CurrencyAgent
from utils.serp_client import ProviderError
from utils.validation import airport_label
from .common import section_title

SUGGESTIONS = ["What is the cheapest flight?", "Which hotel is best?", "What will the weather be like?", "What is the total cost?", "Extend the trip by 2 days"]
FIELD_LABELS = {"origin": "From", "destination": "To", "departure_date": "Departure", "return_date": "Return", "adults": "Adults", "children": "Children", "rooms": "Rooms"}


def _safe(text: str) -> str:
    return text.replace("$", "\\$")


def _current_values(request: Dict[str, Any]) -> Dict[str, Any]:
    return {k: request.get(k) for k in FIELD_LABELS}


def _ask(question: str, report: Dict[str, Any], search: Dict[str, Any]) -> None:
    history: List[Dict[str, str]] = search.setdefault("chat", [])
    rates = None
    if any(w in question.lower() for w in ("convert", "currency", "exchange", "bdt", "eur", "gbp", "inr", "usd")):
        try:
            rates = CurrencyAgent().get_rates(report["request"]["currency"])
        except ProviderError:
            rates = None
    result = AssistantAgent().answer(question, report, history, rates)
    history.append({"role": "user", "content": question})
    history.append({"role": "assistant", "content": result["answer"], "source": result["source"]})
    search["pending"] = {"changes": result["changes"], "clarify": result["clarify"]} if result["changes"] else None


def _dismiss(search: Dict[str, Any]) -> None:
    search["pending"] = None


def render_assistant(report: Dict[str, Any], search: Dict[str, Any], on_apply: Callable[[Dict[str, Any]], None]) -> None:
    sid = search["id"]
    st.markdown(section_title("💬", "Ask about your trip", "answers use only your search results"), unsafe_allow_html=True)
    ai_on = AssistantAgent().llm_configured
    st.caption("Answered by your configured AI model, using only this trip's data." if ai_on
               else "No AI model is configured, so simple built-in rules answer. Add LLM_BASE_URL and LLM_MODEL for free-form answers.")

    cols = st.columns(len(SUGGESTIONS))
    for i, text in enumerate(SUGGESTIONS):
        if cols[i].button(text, key=f"sugg_{sid}_{i}", use_container_width=True):
            _ask(text, report, search)

    for m in search.get("chat", []):
        with st.chat_message(m["role"]):
            st.markdown(_safe(m["content"]))
            if m["role"] == "assistant":
                st.caption("AI model" if m.get("source") == "ai" else "Built-in rules")

    pending = search.get("pending")
    if pending and pending.get("changes"):
        current = _current_values(report["request"])
        with st.container(border=True, key="card_pending"):
            st.markdown("**Proposed trip changes** (nothing changes until you confirm; this runs a new search)")
            for key, new in pending["changes"].items():
                if key == "children_ages":
                    continue
                st.markdown(f"- {FIELD_LABELS.get(key, key)}: `{current.get(key)}` → `{new}`")
            a, b, _ = st.columns([2, 1, 4])
            a.button("✅ Apply and update trip", key=f"apply_{sid}", type="primary", on_click=on_apply, args=(pending["changes"],))
            b.button("Dismiss", key=f"dismiss_{sid}", on_click=_dismiss, args=(search,))

    question = st.chat_input("Ask a follow-up, or say what to change (e.g. return on Dec 10)", key=f"chat_{sid}")
    if question:
        _ask(question, report, search)
        st.rerun()  # redraw so the new messages and any "confirm changes" box appear in order
