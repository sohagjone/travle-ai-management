"""Trip Plan tab: workflow status, key numbers, what changed, and the day-by-day plan."""

from __future__ import annotations

from typing import Any, Dict

import streamlit as st

from utils.report_data import fmt_money
from utils.display import md_link
from .common import diff_snapshots, md_safe, section_title, snapshot, stepper_html


def workflow_steps(report: Dict[str, Any]):
    recs = report["recommendations"]
    weather_days = (report.get("weather") or {}).get("days") or []
    have_cost = bool(report["cost_estimate"]["scenarios"])
    return [
        ("Flights", "ok" if report["flights"] else "warn", f"{len(report['flights'])} options" if report["flights"] else "none found"),
        ("Hotels", "ok" if report["hotels"] else "warn", f"{len(report['hotels'])} options" if report["hotels"] else "none found"),
        ("Attractions", "ok" if report.get("attractions") else "warn", f"{len(report.get('attractions', []))} places" if report.get("attractions") else "none found"),
        ("Weather", "ok" if weather_days else "warn", f"{len(weather_days)} days" if weather_days else "unavailable"),
        ("Trip cost", "ok" if have_cost else "warn", "estimated" if have_cost else "no prices"),
        ("Plan", "ok" if report.get("plan") else "warn", f"{len(report.get('plan', []))} days" if report.get("plan") else "not built"),
    ]


def render_plan(report: Dict[str, Any], search: Dict[str, Any]) -> None:
    currency = report["request"]["currency"]
    st.markdown(stepper_html(workflow_steps(report)), unsafe_allow_html=True)

    previous = search.get("changes_from")
    if previous:
        lines = diff_snapshots(previous, snapshot(report))
        with st.container(border=True, key="card_changes"):
            st.markdown("**🔄 Trip updated. What changed:**")
            if lines:
                for line in lines:
                    st.markdown(f"- {md_safe(line)}")
            else:
                st.caption("The new search returned the same key numbers as before.")

    recs = report["recommendations"]
    scen = (report["cost_estimate"]["scenarios"] or [None])[0]
    days = (report.get("weather") or {}).get("days") or []
    highs = [d["tmax"] for d in days if d.get("tmax") is not None]
    lows = [d["tmin"] for d in days if d.get("tmin") is not None]
    c1, c2, c3, c4 = st.columns(4)
    best_f = next((f for f in report["flights"] if (recs.get("best_flight") or {}).get("option") == f["option"]), None)
    best_h = next((h for h in report["hotels"] if (recs.get("best_hotel") or {}).get("option") == h["option"]), None)
    c1.metric("Recommended flight", fmt_money(best_f["price"], currency) if best_f else "n/a", best_f["airline"] if best_f else None, delta_color="off")
    c2.metric("Recommended hotel", fmt_money(best_h["price_per_night"], currency) + " /night" if best_h and best_h.get("price_per_night") is not None else "n/a", best_h["name"] if best_h else None, delta_color="off")
    c3.metric("Estimated total", fmt_money(scen["total"], currency) if scen else "n/a", "flight + hotel" if scen else None, delta_color="off")
    c4.metric("Weather", f"{min(lows):.0f}° to {max(highs):.0f}°C" if highs and lows else "n/a", "typical" if (report.get("weather") or {}).get("has_typical") else ("forecast" if days else None), delta_color="off")

    st.markdown(section_title("🗓", "Your day-by-day plan", "built from real attractions and weather"), unsafe_allow_html=True)
    plan = report.get("plan") or []
    if not plan:
        st.info("A plan could not be built for these dates.")
        return
    if not report.get("attractions"):
        st.info("No attractions were returned, so the days below only show the weather.")
    for i, day in enumerate(plan):
        w = day.get("weather")
        with st.container(border=True, key=f"card_day_{i}"):
            c_day, c_wx, c_list = st.columns([2, 3, 7], vertical_alignment="center")
            c_day.markdown(f"**{md_safe(day['label'])}**")
            c_day.caption(day["date"])
            if w:
                hi = "n/a" if w.get("tmax") is None else f"{w['tmax']:.0f}°"
                lo = "n/a" if w.get("tmin") is None else f"{w['tmin']:.0f}°"
                c_wx.markdown(f"{w.get('icon', '')} **{md_safe(w.get('summary'))}**")
                c_wx.caption(f"{lo} / {hi} C" + (" · typical" if w.get("mode") == "typical" else " · forecast"))
            else:
                c_wx.caption("No weather data")
            if day["attractions"]:
                for a in day["attractions"]:
                    rating = f" ★ {a['rating']:.1f}" if a.get("rating") is not None else ""
                    link = f" · {md_link(a['map_url'], 'map ↗')}" if a.get("map_url") else ""
                    c_list.markdown(f"📍 **{md_safe(a['name'])}**{rating}{link}")
            else:
                c_list.caption("Free time / travel")
    st.caption("Places are grouped by proximity using their coordinates. Opening hours and ticket prices are not checked.")
