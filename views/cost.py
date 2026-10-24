"""Trip Cost tab: budget calculator (real prices + your own estimates) and currency conversion."""

from __future__ import annotations

from html import escape
from typing import Any, Callable, Dict, Optional

import pandas as pd
import streamlit as st

from agents.currency_agent import COMMON_CURRENCIES, CurrencyAgent
from utils.report_data import fmt_money
from utils.serp_client import ProviderError
from utils.trip_cost import Assumptions, compute_trip_cost
from .common import section_title

COLORS = {"Flights": "#0E8F9C", "Hotel": "#173B5C", "Food": "#F59E0B", "Local transport": "#7C3AED", "Activities": "#EC4899", "Other": "#94A3B8"}


def _bar(budget: Dict[str, Any]) -> str:
    total = budget["total"] or 0
    if total <= 0:
        return ""
    segs, legend = [], []
    for item in budget["items"]:
        pct = 100 * item["amount"] / total
        color = COLORS.get(item["category"], "#94A3B8")
        segs.append(f'<div style="width:{pct:.2f}%;background:{color}" title="{escape(item["category"])}"></div>')
        legend.append(f'<span class="lg"><i style="background:{color}"></i>{escape(item["category"])} {pct:.0f}%</span>')
    return f'<div class="costbar">{"".join(segs)}</div><div class="costlegend">{"".join(legend)}</div>'


def render_cost(report: Dict[str, Any], search: Dict[str, Any], on_budget: Callable[[Optional[Dict[str, Any]], Optional[Assumptions]], None]) -> None:
    sid = search["id"]
    currency = report["request"]["currency"]
    st.markdown(section_title("💰", "Trip cost calculator", "real search prices + your own estimates"), unsafe_allow_html=True)
    if not report["flights"] and not report["hotels"]:
        st.info("There are no flight or hotel prices to calculate a cost from.")
        return

    saved: Assumptions = search.get("assumptions") or Assumptions()
    priced_f = [f for f in report["flights"] if f.get("price") is not None]
    priced_h = [h for h in report["hotels"] if h.get("price_per_night") is not None or h.get("total_price") is not None]
    flight_opts = [None] + [f["option"] for f in priced_f]
    hotel_opts = [None] + [h["option"] for h in priced_h]
    f_by = {f["option"]: f for f in priced_f}
    h_by = {h["option"]: h for h in priced_h}

    with st.form(f"cost_form_{sid}"):
        c1, c2 = st.columns(2)
        flight_choice = c1.selectbox(
            "Flight", flight_opts, index=flight_opts.index(saved.flight_option) if saved.flight_option in flight_opts else 0,
            format_func=lambda o: "Cheapest flight" if o is None else f"#{o} {f_by[o].get('airline') or 'n/a'} - {fmt_money(f_by[o]['price'], currency)}",
        )
        hotel_choice = c2.selectbox(
            "Hotel", hotel_opts, index=hotel_opts.index(saved.hotel_option) if saved.hotel_option in hotel_opts else 0,
            format_func=lambda o: "Cheapest hotel" if o is None else f"#{o} {h_by[o].get('name')} - {fmt_money(h_by[o].get('price_per_night'), currency)}/night",
        )
        st.caption(f"Add your own estimates (in {currency}). Leave 0 to exclude a line. These are your numbers, not provider data.")
        e1, e2, e3, e4 = st.columns(4)
        food = e1.number_input("Food per person per day", min_value=0.0, value=float(saved.food_per_person_per_day), step=5.0)
        transport = e2.number_input("Local transport per day (group)", min_value=0.0, value=float(saved.transport_per_day), step=5.0)
        activities = e3.number_input("Activities and tickets (total)", min_value=0.0, value=float(saved.activities_total), step=10.0)
        other = e4.number_input("Other costs (total)", min_value=0.0, value=float(saved.other_total), step=10.0)
        options = [currency] + [c for c in COMMON_CURRENCIES if c != currency]
        convert_to = st.selectbox("Show the total in", options, index=options.index(saved.convert_to) if saved.convert_to in options else 0)
        submitted = st.form_submit_button("Calculate budget", type="primary")

    assumptions = Assumptions(flight_choice, hotel_choice, food, transport, activities, other, convert_to if convert_to != currency else None)
    if submitted:
        rates = None
        if assumptions.convert_to:
            try:
                rates = CurrencyAgent().get_rates(currency)
            except ProviderError as exc:
                st.warning(f"{exc} Showing the total in {currency} only.")
        budget = compute_trip_cost(report, assumptions, rates, CurrencyAgent.convert)
        on_budget(budget, assumptions)
        st.rerun()

    budget = search.get("budget") or compute_trip_cost(report, Assumptions())
    if budget["total"] is None:
        st.info("No price is available for the selected flight or hotel.")
    else:
        m1, m2, m3 = st.columns(3)
        m1.metric(f"Total ({currency})", fmt_money(budget["total"], currency))
        m2.metric("Per traveller", fmt_money(budget["per_person"], currency) if budget["per_person"] is not None else "n/a")
        conv = budget.get("converted")
        m3.metric(f"Total ({conv['currency']})" if conv else "Converted total", fmt_money(conv["total"], conv["currency"]) if conv else "choose a currency above")
        if conv:
            st.caption(f"1 {currency} = {conv['rate']:.4f} {conv['currency']} · indicative rate from {conv.get('source') or 'n/a'}, updated {conv.get('updated') or 'n/a'}. Not a bank or card rate.")
        if not budget["complete"]:
            st.warning("The total is incomplete: a flight or hotel price is missing, so it is not a full trip cost.")
        st.markdown(_bar(budget), unsafe_allow_html=True)
        rows = []
        for item in budget["items"]:
            row = {"Category": item["category"], "Item": item["label"], "Source": item["basis"], f"Amount ({currency})": item["amount"]}
            if conv:
                row[f"Amount ({conv['currency']})"] = conv["items"].get(item["category"])
            rows.append(row)
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
        st.caption("Flight prices are shown exactly as returned by the provider; confirm on the booking page whether they are per passenger or for the whole party. Hotel taxes and fees may differ.")

    with st.expander("💱 Currency converter"):
        k1, k2, k3 = st.columns(3)
        amount = k1.number_input("Amount", min_value=0.0, value=100.0, step=10.0, key=f"conv_amt_{sid}")
        frm = k2.selectbox("From", COMMON_CURRENCIES, index=COMMON_CURRENCIES.index(currency) if currency in COMMON_CURRENCIES else 0, key=f"conv_from_{sid}")
        to = k3.selectbox("To", COMMON_CURRENCIES, index=COMMON_CURRENCIES.index("BDT"), key=f"conv_to_{sid}")
        if st.button("Convert", key=f"conv_btn_{sid}"):
            try:
                rates = CurrencyAgent().get_rates(frm)
                value = CurrencyAgent.convert(amount, frm, to, rates)
                if value is None:
                    st.warning(f"No rate is available for {to}.")
                else:
                    st.success(f"{fmt_money(amount, frm)} ≈ {fmt_money(value, to)}")
                    st.caption(f"Indicative rate from {rates.get('source')}, updated {rates.get('updated') or 'n/a'}.")
            except ProviderError as exc:
                st.error(str(exc))
