"""Tourist attractions tab (cards with photos, filters, map links)."""

from __future__ import annotations

from typing import Any, Dict

import streamlit as st

from utils.display import md_link
from .common import md_safe, section_title

SORTS = {
    "Best rated": lambda a: (a.get("rating") is None, -(a.get("rating") or 0), -(a.get("reviews") or 0)),
    "Most reviewed": lambda a: (a.get("reviews") is None, -(a.get("reviews") or 0)),
    "Name (A to Z)": lambda a: (a.get("name") or "").lower(),
}


def render_attractions(report: Dict[str, Any], sid: str) -> None:
    items = report.get("attractions") or []
    city = report["request"].get("destination_city") or report["request"]["destination"]
    st.markdown(section_title("🎯", f"Things to see in {city}", "Google Maps results"), unsafe_allow_html=True)
    if not items:
        st.info("No attractions were returned for this destination.")
        return

    with st.expander("🔎 Filter attractions", expanded=False):
        f1, f2, f3 = st.columns(3)
        min_rating = f1.select_slider("Minimum rating", [0.0, 4.0, 4.3, 4.5, 4.7], 0.0,
                                      format_func=lambda v: "Any" if v == 0 else f"{v}+ ★", key=f"aflt_rating_{sid}")
        types = sorted({a["type"] for a in items if a.get("type")})
        picked = f2.multiselect("Type", types, key=f"aflt_type_{sid}", placeholder="Any type")
        query = f3.text_input("Name contains", key=f"aflt_name_{sid}", placeholder="e.g. museum")
    shown = [a for a in items
             if (not min_rating or (a.get("rating") is not None and a["rating"] >= min_rating))
             and (not picked or a.get("type") in picked)
             and (not query.strip() or query.strip().lower() in (a.get("name") or "").lower())]
    sort = st.selectbox("Sort by", list(SORTS), key=f"asort_{sid}")
    shown = sorted(shown, key=SORTS[sort])
    st.caption(f"Showing {len(shown)} of {len(items)} places.")
    if not shown:
        st.info("No places match these filters.")
        return
    limit = len(shown) if len(shown) <= 9 else (len(shown) if st.toggle(f"Show all {len(shown)} places (showing 9)", key=f"ashow_{sid}") else 9)
    for row_start in range(0, limit, 3):
        cols = st.columns(3)
        for offset, a in enumerate(shown[row_start: min(row_start + 3, limit)]):
            with cols[offset]:
                with st.container(border=True, key=f"card_attr_{row_start + offset}"):
                    if a.get("thumbnail"):
                        st.image(a["thumbnail"], use_container_width=True)
                    else:
                        st.markdown('<div class="photo-ph">🏛<small>no photo</small></div>', unsafe_allow_html=True)
                    st.markdown(f"**{md_safe(a['name'])}**")
                    bits = []
                    if a.get("type"):
                        bits.append(md_safe(a["type"]))
                    if a.get("rating") is not None:
                        reviews = f" ({a['reviews']:,})" if isinstance(a.get("reviews"), int) else ""
                        bits.append(f"★ {a['rating']:.1f}{reviews}")
                    if bits:
                        st.caption(" · ".join(bits))
                    if a.get("address"):
                        st.caption(md_safe(a["address"]))
                    if a.get("map_url"):
                        st.markdown(md_link(a["map_url"], "Open in Google Maps ↗"))
    st.caption("Results come from Google Maps via SerpAPI. Check opening hours and ticket prices before you go.")
