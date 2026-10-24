"""AI Travel Agent page (Streamlit opens it automatically from the sidebar because it lives in pages/).

Tabs:
  1. Chat with the agent        - tool-using AI agent with trip memory and follow-up questions
  2. Plan a trip (workflow)     - the complete workflow without an AI model, plus "change a requirement"
  3. Agent vs chatbot           - the same question to a plain chatbot and to the agent
  4. How the tools work together - diagram, tool list and the live trace of every tool call
"""

import os
import sys
from datetime import date, timedelta
from typing import Any, Dict, List

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:  # lets this page import the project's packages when opened directly
    sys.path.insert(0, ROOT)

from agents.base_agent import LLMUnavailableError  # noqa: E402
from agents.travel_agent import TraditionalChatbot, TravelAgent  # noqa: E402
from agents.trip_planner import STEP_LABELS, TripPlanner  # noqa: E402
from utils.config import get_secret, redact  # noqa: E402
from utils.export_reports import build_all_exports  # noqa: E402
from utils.report_data import fmt_money  # noqa: E402
from utils.styles import CSS  # noqa: E402
from utils.travel_tools import TOOL_CATALOG, TravelTools  # noqa: E402
from utils.trip_state import describe_changes  # noqa: E402
from utils.validation import airport_choices, code_from_label, validate_travel_request  # noqa: E402

load_dotenv()

EXAMPLE_PROMPTS = [
    "Plan a week in Amsterdam for 2 adults flying from Madrid, leaving 30 days from now. Hotels 4 stars. What will it cost?",
    "What's the weather like there, and what should we see?",
    "Actually make it 3 adults and stay two days longer. What changes in the price?",
    "Show the total in EUR, and tell me if we need a visa from the UK.",
]


# ------------------------------------------------------------------ helpers
def chat_safe(text: str) -> str:
    """`$` would start LaTeX in Streamlit markdown; prices are full of them."""
    return (text or "").replace("$", "\\$")


def get_ctx() -> Dict[str, Any]:
    if "agent_ctx" not in st.session_state:
        tools = TravelTools()
        st.session_state["agent_ctx"] = {
            "tools": tools, "agent": TravelAgent(tools), "messages": [], "last_run": None,
            "settings": {"include_tips": True, "convert_total_to": "", "food": 0.0, "activities": 0.0, "transport": 0.0},
            "change_log": None, "compare": None, "exports": None,
        }
    return st.session_state["agent_ctx"]


def reset_all() -> None:
    st.session_state.pop("agent_ctx", None)


def render_calls(calls: List[Any]) -> None:
    if not calls:
        return
    with st.expander(f"🔧 {len(calls)} tool call(s) used", expanded=False):
        for i, c in enumerate(calls, start=1):
            icon = "✅" if c.ok else "⚠️"
            cache = " · reused saved result" if c.cached else ""
            st.markdown(f"**{i}. {icon} `{c.name}`** · {c.seconds}s{cache}")
            if c.arguments:
                st.caption("Arguments: " + ", ".join(f"{k}={v}" for k, v in c.arguments.items()))
            st.caption(c.preview)
            st.json(c.result, expanded=False)


def trace_frame(tools: TravelTools) -> pd.DataFrame:
    return pd.DataFrame([
        {"#": i, "Who chose it": "AI agent" if c.source == "agent" else "Fixed workflow", "Tool": c.name,
         "Arguments": ", ".join(f"{k}={v}" for k, v in c.arguments.items()) or "-", "OK": "yes" if c.ok else "no",
         "Seconds": c.seconds, "Reused": "yes" if c.cached else "", "Result": c.preview[:90]}
        for i, c in enumerate(tools.trace, start=1)
    ])


# ------------------------------------------------------------------ sidebar
def render_sidebar(ctx: Dict[str, Any]) -> None:
    agent: TravelAgent = ctx["agent"]
    with st.sidebar:
        st.markdown("### Status")
        st.write(("✅" if agent.available else "⚠️") + " AI model: " + (agent.model_name if agent.available else "not configured"))
        st.write(("✅" if get_secret("SERPAPI_API_KEY") else "⚠️") + " SerpAPI key (flights, hotels, places, web search)")
        st.write("✅ Weather and exchange rates need no key")
        st.markdown("### Trip memory")
        st.code(ctx["tools"].state.summary(), language=None)
        stale = ctx["tools"].stale_results()
        if stale:
            st.warning("Out of date after your change: " + ", ".join(stale))
        st.button("Start over (clear trip and chat)", on_click=reset_all)


# --------------------------------------------------------------- tab 1: chat
def render_chat(ctx: Dict[str, Any]) -> None:
    agent: TravelAgent = ctx["agent"]
    st.markdown("#### Chat with the travel agent")
    st.caption(
        "The agent remembers the trip, so follow-ups like “what's the weather there?” or “make it 3 adults” just work. "
        "Open **🔧 tool calls** under any answer to see exactly what it looked up."
    )
    if not agent.available:
        st.info("The chat agent needs an AI model that supports tool calling. Set LLM_BASE_URL and LLM_MODEL "
                "(see README). The **Plan a trip** tab works without one.")

    with st.expander("Try these in order (a typical conversation)"):
        for i, text in enumerate(EXAMPLE_PROMPTS):
            if st.button(text, key=f"ex_{i}", disabled=not agent.available):
                st.session_state["_pending_prompt"] = text

    history = st.container()
    typed = st.chat_input("Ask about flights, hotels, weather, costs…", disabled=not agent.available, key="agent_chat_input")
    prompt = typed or st.session_state.pop("_pending_prompt", None)
    if prompt:
        ctx["messages"].append({"role": "user", "content": prompt, "calls": []})
        with st.spinner("The agent is working (it may call several tools)…"):
            turn = agent.chat(prompt)
        if turn.error:
            ctx["messages"].append({"role": "assistant", "content": f"⚠️ {turn.error}", "calls": turn.calls})
        else:
            ctx["messages"].append({"role": "assistant", "content": turn.reply, "calls": turn.calls})
    with history:
        for m in ctx["messages"]:
            with st.chat_message(m["role"]):
                st.markdown(chat_safe(m["content"]))
                render_calls(m.get("calls") or [])


# ------------------------------------------------------ tab 2: workflow + updates
def _apply_form_to_state(tools: TravelTools, form: Dict[str, Any]) -> List[str]:
    errors = validate_travel_request(
        form["origin"], form["destination"], form["departure"], form["return"],
        form["adults"], form["children"], form["rooms"], form["children_ages"],
    )
    if errors:
        return errors
    outcome = tools.state.update(
        origin=form["origin"], destination=form["destination"], departure_date=str(form["departure"]),
        return_date=str(form["return"]), adults=form["adults"], children=form["children"],
        children_ages=form["children_ages"], rooms=form["rooms"], currency=form["currency"],
        budget=form["budget"] or 0, hotel_class=form["stars"], interests=form["interests"],
    )
    return list(outcome["rejected"].values())


def render_plan_form(ctx: Dict[str, Any]) -> None:
    tools: TravelTools = ctx["tools"]
    today = date.today()
    labels, _ = airport_choices()
    with st.container(border=True):
        st.markdown("##### Trip requirements")
        c1, c2 = st.columns(2)
        origin = c1.selectbox("From", labels, index=None, key="ag_origin", placeholder="Type a code or airport name, e.g. DAC")
        destination = c2.selectbox("To", labels, index=None, key="ag_destination", placeholder="Type a code or airport name, e.g. AMS")
        d1, d2, t1, t2, t3 = st.columns([1.3, 1.3, 1, 1, 1])
        departure = d1.date_input("Departure", today + timedelta(days=30), min_value=today, key="ag_dep")
        ret = d2.date_input("Return", today + timedelta(days=37), min_value=today, key="ag_ret")
        adults = int(t1.number_input("Adults", 1, 9, 1, key="ag_adults"))
        children = int(t2.number_input("Children", 0, 8, 0, key="ag_children"))
        rooms = int(t3.number_input("Rooms", 1, 8, 1, key="ag_rooms"))
        ages: List[int] = []
        if children:
            cols = st.columns(min(children, 4))
            for i in range(children):
                with cols[i % len(cols)]:
                    ages.append(int(st.number_input(f"Child {i + 1} age", 0, 17, 8, key=f"ag_age_{i}")))
        e1, e2, e3, e4 = st.columns(4)
        currency = e1.selectbox("Currency for prices", ["USD", "EUR", "GBP", "BDT", "INR", "JPY", "AUD", "CAD"], key="ag_currency")
        budget = e2.number_input("Total budget (optional)", min_value=0.0, value=0.0, step=100.0, key="ag_budget")
        stars = e3.multiselect("Hotel stars", ["2", "3", "4", "5"], key="ag_stars", placeholder="Any")
        interests = e4.multiselect("Interests", ["museums", "food", "beaches", "history", "nature", "nightlife", "shopping", "family activities"],
                                   key="ag_interests", placeholder="General sightseeing")
        f1, f2, f3, f4 = st.columns(4)
        food = f1.number_input("Food / person / day (optional)", 0.0, step=5.0, key="ag_food")
        activities = f2.number_input("Activities / person / day (optional)", 0.0, step=5.0, key="ag_activities")
        transport = f3.number_input("Local transport / day (optional)", 0.0, step=5.0, key="ag_transport")
        convert_to = f4.selectbox("Also show total in", ["(same)", "USD", "EUR", "GBP", "BDT", "INR", "JPY"], key="ag_convert")
        include_tips = st.checkbox("Include a web search for local tips (uses 1 extra SerpAPI search)", value=True, key="ag_tips")
        go = st.button("Plan my trip", type="primary", key="ag_plan")

    if go:
        form = {"origin": code_from_label(origin), "destination": code_from_label(destination), "departure": departure, "return": ret,
                "adults": adults, "children": children, "children_ages": ages, "rooms": rooms, "currency": currency,
                "budget": budget, "stars": ",".join(stars), "interests": interests}
        problems = _apply_form_to_state(tools, form)
        if problems:
            for message in problems:
                st.error(message)
            return
        ctx["settings"] = {"include_tips": include_tips, "convert_total_to": "" if convert_to == "(same)" else convert_to,
                           "food": food, "activities": activities, "transport": transport}
        ctx["change_log"] = None
        ctx["exports"] = None
        with st.spinner("Running the workflow: flights, hotels, weather, attractions…"):
            ctx["last_run"] = run_plan(ctx, force=True)


def run_plan(ctx: Dict[str, Any], force: bool = False):
    s = ctx["settings"]
    return TripPlanner(ctx["tools"]).plan(
        include_tips=s["include_tips"], convert_total_to=s["convert_total_to"], food_per_person_per_day=s["food"],
        activities_per_person_per_day=s["activities"], local_transport_per_day=s["transport"], force=force,
    )


def render_change_panel(ctx: Dict[str, Any]) -> None:
    tools: TravelTools = ctx["tools"]
    state = tools.state
    if not (state.departure_date and state.return_date):
        return
    today = date.today()
    with st.expander("✏️ Change a requirement (only what is affected is searched again)", expanded=ctx["change_log"] is not None):
        c1, c2, c3 = st.columns(3)
        new_ret = c1.date_input("New return date", date.fromisoformat(state.return_date), min_value=today, key="chg_ret")
        new_adults = int(c2.number_input("Adults", 1, 9, state.adults, key="chg_adults"))
        new_stars = c3.multiselect("Hotel stars", ["2", "3", "4", "5"], default=[s for s in state.hotel_class.split(",") if s], key="chg_stars")
        d1, d2, d3 = st.columns(3)
        new_dep = d1.date_input("New departure date", date.fromisoformat(state.departure_date), min_value=today, key="chg_dep")
        new_currency = d2.selectbox("Currency", ["USD", "EUR", "GBP", "BDT", "INR", "JPY", "AUD", "CAD"],
                                    index=["USD", "EUR", "GBP", "BDT", "INR", "JPY", "AUD", "CAD"].index(state.currency) if state.currency in ["USD", "EUR", "GBP", "BDT", "INR", "JPY", "AUD", "CAD"] else 0,
                                    key="chg_currency")
        new_budget = d3.number_input("Budget", 0.0, value=float(state.budget or 0), step=100.0, key="chg_budget")
        if st.button("Apply change and re-plan", key="chg_apply"):
            outcome = state.update(departure_date=str(new_dep), return_date=str(new_ret), adults=new_adults,
                                   hotel_class=",".join(new_stars), currency=new_currency, budget=new_budget)
            stale = tools.stale_results()
            with st.spinner("Re-running only what changed…"):
                run = run_plan(ctx)
            ctx["last_run"] = run
            ctx["exports"] = None
            ctx["change_log"] = {"changed": describe_changes(outcome["changed"]), "rejected": list(outcome["rejected"].values()),
                                 "stale": stale, "ran": run.ran, "reused": run.reused}
            st.rerun()
    log = ctx["change_log"]
    if log:
        if log["rejected"]:
            for message in log["rejected"]:
                st.error(message)
        if not log["changed"]:
            st.info("Nothing changed, so nothing was searched again.")
        else:
            st.success("Changed: " + "; ".join(log["changed"]))
            st.markdown(
                "**Searched again:** " + (", ".join(STEP_LABELS[s] for s in log["ran"]) or "nothing") +
                "  \n**Reused (still valid):** " + (", ".join(STEP_LABELS[s] for s in log["reused"]) or "nothing")
            )


def _money(value: Any, currency: str) -> str:
    return fmt_money(value, currency)


def render_results(ctx: Dict[str, Any]) -> None:
    tools: TravelTools = ctx["tools"]
    run = ctx["last_run"]
    if not tools.results:
        return
    currency = tools.state.currency
    st.divider()
    stale = tools.stale_results()
    if stale:
        st.warning("These results are out of date because the trip changed: " + ", ".join(stale))
    if run:
        for step, reason in run.skipped.items():
            st.info(f"{STEP_LABELS[step]} skipped: {reason}.")
        for step, message in run.errors.items():
            st.error(f"{STEP_LABELS.get(step, step.title())}: {message}")

    cost = tools.last_cost
    report = tools.report()
    t_cost, t_fl, t_ho, t_wx, t_at, t_tips = st.tabs(["💰 Cost", "✈️ Flights", "🏨 Hotels", "🌤 Weather", "📍 Attractions", "💡 Tips"])

    with t_cost:
        if not cost:
            st.info("No cost yet - a flight or hotel search is needed first.")
        else:
            m1, m2, m3 = st.columns(3)
            m1.metric("Estimated total", _money(cost["total"], currency))
            m2.metric("Per traveller", _money(cost["per_person"], currency))
            if cost.get("converted"):
                m3.metric(f"Total in {cost['converted']['currency']}", f"{cost['converted']['total']:,.2f}")
            elif cost.get("budget"):
                b = cost["budget"]
                m3.metric("Budget", b["status"], f"{'-' if b['status'] == 'over budget' else '+'}{_money(b['difference'], currency)}", delta_color="inverse" if b["status"] == "over budget" else "normal")
            for item in cost["items"]:
                st.text(f"{item['label']}: {_money(item['amount'], currency)}")
                st.caption(item["basis"])
            if cost.get("converted"):
                c = cost["converted"]
                st.caption(f"Exchange rate 1 {currency} = {c['rate']:.4f} {c['currency']} ({c['source']}, {c['as_of'] or 'latest'}). Banks add their own margin.")
            if cost.get("budget") and cost.get("converted"):
                b = cost["budget"]
                st.caption(f"Budget check: {b['status']} by {_money(b['difference'], currency)}.")
            for w in cost["warnings"]:
                st.warning(w)
            with st.expander("What is NOT included"):
                for n in cost["not_included"]:
                    st.markdown(f"- {n}")

    with t_fl:
        rows = report["flights"]
        if not rows:
            st.info("No flights found.")
        else:
            st.dataframe(pd.DataFrame([{
                "Option": f["option"], "Airline": f["airline"], "From": f["departure_airport"], "Departure": f["departure"],
                "To": f["arrival_airport"], "Arrival": f["arrival"], "Duration": f["duration"], "Stops": f["stops"],
                f"Price ({currency})": f["price"], "Link": f["booking_url"]} for f in rows]),
                hide_index=True, column_config={"Link": st.column_config.LinkColumn("Google Flights", display_text="Open")})
            st.caption("Prices are search results, not confirmed fares.")

    with t_ho:
        rows = report["hotels"]
        if not rows:
            st.info("No hotels found.")
        else:
            st.dataframe(pd.DataFrame([{
                "Option": h["option"], "Hotel": h["name"], "Class": h["hotel_class"], "Rating": h["rating"], "Reviews": h["reviews"],
                f"Per night ({currency})": h["price_per_night"], f"Total ({currency})": h["total_price"],
                "Amenities": h["amenities"], "Link": h["booking_url"]} for h in rows]),
                hide_index=True, column_config={"Link": st.column_config.LinkColumn("Website", display_text="Open")})

    with t_wx:
        wx = tools.data("weather")
        if not wx:
            st.info("No weather result yet.")
        else:
            (st.info if wx["mode"] == "forecast" else st.warning)(wx["note"])
            s = wx["summary"]
            m1, m2, m3 = st.columns(3)
            m1.metric("Average high", f"{s['avg_high_c']}°C" if s["avg_high_c"] is not None else "n/a")
            m2.metric("Average low", f"{s['avg_low_c']}°C" if s["avg_low_c"] is not None else "n/a")
            m3.metric("Rainy days", f"{s['rainy_days']} of {s['days']}")
            st.dataframe(pd.DataFrame([{"Date": d["date"], "Weather": d["condition"], "High °C": d["temp_max_c"], "Low °C": d["temp_min_c"],
                                        "Rain mm": d["rain_mm"]} for d in wx["daily"]]), hide_index=True)

    with t_at:
        at = tools.data("attractions")
        if not at or not at["places"]:
            st.info("No attractions found.")
        else:
            st.dataframe(pd.DataFrame([{"Place": p["name"], "Type": p.get("type"), "Rating": p.get("rating"), "Reviews": p.get("reviews"),
                                        "Address": p.get("address"), "Interest": p.get("interest")} for p in at["places"]]), hide_index=True)

    with t_tips:
        tips = tools.data("tips")
        if not tips:
            st.info("Tips were not searched.")
        else:
            if tips.get("quick_answer"):
                st.markdown(chat_safe(tips["quick_answer"]))
            for r in tips["results"]:
                st.markdown(f"**[{r['title']}]({r['link']})**  \n{chat_safe(r.get('snippet') or '')}")

    # downloads reuse the same exporters as the main page
    if not stale and (report["flights"] or report["hotels"]):
        st.markdown("##### Download")
        if st.button("Prepare download files", key="ag_prep"):
            ctx["exports"] = build_all_exports(report)
        if ctx["exports"]:
            cols = st.columns(4)
            for i, key in enumerate(["pdf", "xlsx", "docx", "json"]):
                ex = ctx["exports"][key]
                with cols[i]:
                    if ex.ok:
                        st.download_button(f"⬇ {ex.label}", ex.data, ex.filename, ex.mime, key=f"ag_dl_{key}")
                    else:
                        st.error(ex.error or f"{ex.label} could not be created.")


def render_workflow(ctx: Dict[str, Any]) -> None:
    st.markdown("#### Complete travel planning workflow")
    st.caption(
        "No AI model needed: a fixed recipe runs the same tools the agent uses - flights, hotels, weather, attractions and tips "
        "in parallel, then the cost and currency conversion. Change a requirement afterwards and only the affected searches run again."
    )
    render_plan_form(ctx)
    render_change_panel(ctx)
    render_results(ctx)


# ------------------------------------------------------- tab 3: agent vs chatbot
COMPARISON = """
| | Traditional chatbot | AI agent (this app) |
|---|---|---|
| **Knowledge** | Only what it learned in training or was scripted | Training **plus live data** fetched with tools |
| **Actions** | Replies with text | Calls tools (flights, hotels, weather, web, currency, cost) and reads the results |
| **Steps** | One question → one answer | A loop: think → call tools → read results → decide the next step → answer |
| **Memory** | Often forgets, or just re-reads chat text | Chat history **plus a structured trip memory** the tools use |
| **When you change your mind** | Starts over, or answers from old numbers | Updates the trip, finds **which results are stale**, searches only those again |
| **Arithmetic and rates** | May guess | Uses a calculator tool and live exchange rates |
| **When something fails** | Often answers anyway | Reads the tool's error, fixes the input or asks you |
"""


def render_compare(ctx: Dict[str, Any]) -> None:
    st.markdown("#### AI agent vs traditional chatbot")
    st.markdown(COMPARISON)
    chatbot = TraditionalChatbot()
    if not chatbot.available:
        st.info("To run the live side-by-side test, configure an AI model that supports tool calling (LLM_BASE_URL, LLM_MODEL).")
        return
    d1 = date.today() + timedelta(days=30)
    default = (f"I live in Madrid and want to visit Amsterdam from {d1} to {d1 + timedelta(days=7)} with 2 adults. "
               "Find flights and a 4-star hotel, tell me the weather and two things to see, and give the total cost in EUR.")
    question = st.text_area("Ask both the same question", default, height=100, key="cmp_q")
    if st.button("Run both", key="cmp_go"):
        with st.spinner("Asking the chatbot and the agent…"):
            tools = TravelTools()
            agent = TravelAgent(tools)
            result: Dict[str, Any] = {"question": question}
            try:
                result["chatbot"] = chatbot.reply(question)
            except LLMUnavailableError as exc:
                result["chatbot"] = f"⚠️ {exc}"
            turn = agent.chat(question)
            result["agent"] = f"⚠️ {turn.error}" if turn.error else turn.reply
            result["calls"] = turn.calls
        ctx["compare"] = result
    res = ctx.get("compare")
    if res:
        a, b = st.columns(2)
        with a:
            st.markdown("##### 💬 Traditional chatbot (no tools)")
            st.markdown(chat_safe(res["chatbot"]))
        with b:
            st.markdown("##### 🤖 AI agent (with tools)")
            st.markdown(chat_safe(res["agent"]))
            render_calls(res["calls"])
        st.caption("Look for numbers the chatbot gives without a source - prices, weather, rates - and compare them with the tool results.")


# ---------------------------------------------- tab 4: how tools work together
DOT = """
digraph G {
  rankdir=LR; bgcolor="transparent";
  node [shape=box, style="rounded,filled", fillcolor="#EAF2F8", color="#5D6D7E", fontname="Helvetica", fontsize=11];
  edge [color="#5D6D7E", fontname="Helvetica", fontsize=9];
  user [label="Traveller", fillcolor="#FDEBD0"];
  agent [label="AI agent\\n(plans, calls tools,\\nreads results)", fillcolor="#D5F5E3"];
  memory [label="Trip memory\\n(route, dates, travellers,\\nbudget, interests)", shape=cylinder, fillcolor="#FCF3CF"];
  user -> agent [label="request or change"];
  agent -> user [label="answer + links"];
  agent -> memory [dir=both, label="read / update"];
  agent -> flights [label="1"]; agent -> hotels [label="2"]; agent -> weather [label="3"]; agent -> attractions; agent -> web;
  agent -> cost [label="then"]; agent -> fx;
  flights [label="search_flights\\nGoogle Flights"]; hotels [label="search_hotels\\nGoogle Hotels"];
  weather [label="get_weather\\nOpen-Meteo"]; attractions [label="find_attractions\\nGoogle Maps"];
  web [label="web_search\\nvisas, events, tips"]; cost [label="calculate_trip_cost\\nexact arithmetic"]; fx [label="convert_currency\\nlive rates"];
  flights -> cost [style=dashed]; hotels -> cost [style=dashed]; fx -> cost [style=dashed, dir=back];
}
"""

WALKTHROUGH = """
**One request, many tools.** “Plan a week in Amsterdam from Madrid for 2 adults, show the total in EUR.”

1. `update_trip_details` - saves origin, destination, dates and travellers into the trip memory.
2. `search_flights`, `search_hotels`, `get_weather`, `find_attractions` - independent, so the agent calls them **together**.
3. `calculate_trip_cost` - needs the flight and hotel results from step 2, so it must come **after** them.
4. `convert_currency` (inside the cost tool) - turns the total into EUR with a live rate.
5. The agent writes one answer from these results. Later: *“make it 3 adults”* → `update_trip_details` marks flights and hotels **stale**
   (weather and attractions are not affected), the agent searches only those two again, then recalculates the cost.
"""


def render_how(ctx: Dict[str, Any]) -> None:
    tools: TravelTools = ctx["tools"]
    st.markdown("#### How multiple tools work together")
    st.graphviz_chart(DOT)
    st.markdown(WALKTHROUGH)
    st.markdown("##### The tools")
    st.dataframe(pd.DataFrame(TOOL_CATALOG).rename(columns={"tool": "Tool", "purpose": "What it does", "data": "Data source", "needs_key": "Key needed"}), hide_index=True)
    st.markdown("##### Workflow vs agent")
    st.markdown("A **workflow** (the *Plan a trip* tab) follows a fixed recipe you wrote. An **agent** (the *Chat* tab) picks the tools and the order itself "
                "from the situation. Both use the same tools and the same trip memory.")
    st.markdown("##### Live trace of every tool call in this session")
    if tools.trace:
        st.dataframe(trace_frame(tools), hide_index=True)
    else:
        st.info("No tool has been called yet. Chat with the agent or run the workflow, then come back here.")


# --------------------------------------------------------------------- main
def main() -> None:
    st.set_page_config(page_title="AI Travel Agent", page_icon="🧭", layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)
    st.title("🧭 AI Travel Agent")
    ctx = get_ctx()
    render_sidebar(ctx)
    t_chat, t_plan, t_cmp, t_how = st.tabs(["💬 Chat agent", "🧳 Plan a trip (workflow)", "⚖️ Agent vs chatbot", "🔌 How the tools work together"])
    with t_chat:
        render_chat(ctx)
    with t_plan:
        render_workflow(ctx)
    with t_cmp:
        render_compare(ctx)
    with t_how:
        render_how(ctx)


main()
