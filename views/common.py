"""Small UI helpers shared by all the result tabs."""

from __future__ import annotations

import re
from html import escape
from typing import Any, Dict, List, Optional

from utils.report_data import fmt_money


def md_safe(text: Any) -> str:
    """Escape Markdown (and `$`, which Streamlit would treat as LaTeX) in provider text."""
    return re.sub(r"([\\`*_{}\[\]()#+\-.!|<>$~])", r"\\\1", "" if text is None else str(text))


def badges(*pairs) -> str:
    return " ".join(f":{color}-badge[{text}]" for color, text in pairs if text)


def stepper_html(steps: List[tuple]) -> str:
    """Workflow ribbon. steps = [(label, status, detail)], status in ok | warn."""
    parts = []
    for label, status, detail in steps:
        icon = "✓" if status == "ok" else "!"
        parts.append(
            f'<div class="step {status}"><span class="dot">{icon}</span>'
            f'<span class="txt"><b>{escape(label)}</b><small>{escape(detail)}</small></span></div>'
        )
    return '<div class="stepper">' + "".join(parts) + "</div>"


def section_title(icon: str, title: str, subtitle: str = "") -> str:
    sub = f'<span class="sub">{escape(subtitle)}</span>' if subtitle else ""
    return f'<div class="section-title"><span class="ico">{icon}</span>{escape(title)}{sub}</div>'


# ---------------------------------------------------------- trip snapshots
def _cheapest_flight(report) -> Optional[float]:
    prices = [f["price"] for f in report["flights"] if f.get("price") is not None]
    return min(prices) if prices else None


def _cheapest_hotel_night(report) -> Optional[float]:
    prices = [h["price_per_night"] for h in report["hotels"] if h.get("price_per_night") is not None]
    return min(prices) if prices else None


def snapshot(report: Dict[str, Any]) -> Dict[str, Any]:
    req = report["request"]
    scen = (report["cost_estimate"]["scenarios"] or [None])[0]
    return {
        "currency": req["currency"],
        "Route": f"{req['origin']} → {req['destination']}",
        "Departure": req["departure_date"], "Return": req["return_date"], "Nights": req["nights"],
        "Adults": req["adults"], "Children": req["children"], "Rooms": req["rooms"],
        "Cheapest flight": _cheapest_flight(report),
        "Cheapest hotel per night": _cheapest_hotel_night(report),
        "Estimated total (flight + hotel)": scen["total"] if scen else None,
    }


def diff_snapshots(old: Dict[str, Any], new: Dict[str, Any]) -> List[str]:
    cur = new["currency"]
    lines = []
    for key, value in new.items():
        if key == "currency" or old.get(key) == value:
            continue
        before, after = old.get(key), value
        if isinstance(after, (int, float)) and isinstance(before, (int, float)) and "$" not in key and key in (
            "Cheapest flight", "Cheapest hotel per night", "Estimated total (flight + hotel)"
        ):
            delta = after - before
            lines.append(f"{key}: {fmt_money(before, cur)} → {fmt_money(after, cur)} ({'+' if delta >= 0 else '-'}{fmt_money(abs(delta), cur)})")
        elif key in ("Cheapest flight", "Cheapest hotel per night", "Estimated total (flight + hotel)"):
            lines.append(f"{key}: {fmt_money(before, cur) if before is not None else 'n/a'} → {fmt_money(after, cur) if after is not None else 'n/a'}")
        else:
            lines.append(f"{key}: {before} → {after}")
    return lines
