"""Weather tab: day tiles, temperature chart, packing hints."""

from __future__ import annotations

from typing import Any, Dict

import pandas as pd
import streamlit as st

from .common import md_safe, section_title


def _t(value, unit: str) -> str:
    if value is None:
        return "n/a"
    return f"{value * 9 / 5 + 32:.0f}°F" if unit == "°F" else f"{value:.0f}°C"


def render_weather(report: Dict[str, Any], sid: str) -> None:
    city = report["request"].get("destination_city") or report["request"]["destination"]
    st.markdown(section_title("🌤", f"Weather in {city}", "Open-Meteo"), unsafe_allow_html=True)
    w = report.get("weather") or {}
    days = w.get("days") or []
    if not days:
        st.info("No weather data was available for these dates.")
        return
    unit = st.radio("Temperature unit", ["°C", "°F"], horizontal=True, key=f"wx_unit_{sid}", label_visibility="collapsed")
    if w.get("has_typical"):
        st.info("Dates more than about 15 days away show **typical weather**: the average of the same dates in the last 3 years. It is not a forecast.")

    for row_start in range(0, len(days), 4):
        cols = st.columns(4)
        for offset, d in enumerate(days[row_start: row_start + 4]):
            with cols[offset]:
                with st.container(border=True, key=f"card_wx_{row_start + offset}"):
                    st.caption(f"{d['date']} · {'typical' if d.get('mode') == 'typical' else 'forecast'}")
                    st.markdown(f"## {d.get('icon', '')}")
                    st.markdown(f"**{md_safe(d.get('summary'))}**")
                    st.markdown(f"{_t(d.get('tmax'), unit)} / {_t(d.get('tmin'), unit)}")
                    if d.get("rain_chance") is not None:
                        st.caption(f"Rain on {d['rain_chance']}% of past years")
                    elif d.get("precip") is not None:
                        st.caption(f"Rain: {d['precip']:.1f} mm")

    df = pd.DataFrame({"Date": [d["date"] for d in days],
                       f"High ({unit})": [None if d.get("tmax") is None else (d["tmax"] * 9 / 5 + 32 if unit == "°F" else d["tmax"]) for d in days],
                       f"Low ({unit})": [None if d.get("tmin") is None else (d["tmin"] * 9 / 5 + 32 if unit == "°F" else d["tmin"]) for d in days]}).set_index("Date")
    st.line_chart(df)

    highs = [d["tmax"] for d in days if d.get("tmax") is not None]
    lows = [d["tmin"] for d in days if d.get("tmin") is not None]
    wet = [d for d in days if (d.get("rain_chance") or 0) >= 50 or (d.get("precip") or 0) >= 1]
    hints = []
    if lows and min(lows) < 10:
        hints.append("🧥 Lows below 10°C: pack a warm jacket and layers.")
    if highs and max(highs) >= 28:
        hints.append("🕶 Highs of 28°C or more: light clothes, sunscreen and water.")
    if wet:
        hints.append(f"☂️ Rain is likely on {len(wet)} of {len(days)} days: bring an umbrella or rain jacket.")
    if hints:
        st.markdown("**Packing hints** (from the numbers above)")
        for h in hints:
            st.markdown(f"- {h}")
    st.caption("Weather data by Open-Meteo.com (CC BY 4.0).")
