"""Tests for the AI travel agent. EVERYTHING external is mocked: SerpAPI, Open-Meteo, exchange rates and the AI model."""
import json
import os
from datetime import date, timedelta
from types import SimpleNamespace as NS
from unittest.mock import patch

import pytest

from agents.base_agent import LLMUnavailableError
from agents.travel_agent import MAX_TOOL_ROUNDS, TraditionalChatbot, TravelAgent
from agents.trip_planner import TripPlanner
from tests.fixtures import FLIGHTS_RAW, HOTELS_RAW
from utils import travel_apis
from utils.airport_resolver import resolve_airport
from utils.serp_client import ProviderError
from utils.travel_tools import TravelTools
from utils.trip_costs import calculate_trip_cost
from utils.trip_state import TripState

TODAY = date.today()
D1 = TODAY + timedelta(days=40)       # far ahead: weather falls back to "typical"
D2 = D1 + timedelta(days=7)
MAIN_PAGE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pages", "1_AI_Travel_Agent.py")

MAPS_RAW = {"local_results": [
    {"title": "Rijksmuseum", "rating": 4.7, "reviews": 90000, "type": "Art museum", "address": "Museumstraat 1"},
    {"title": "Vondelpark", "rating": 4.6, "reviews": 120000, "type": "Park", "address": "Amsterdam"},
    {"title": "Unrated Spot", "type": "Square"},
]}
WEB_RAW = {"answer_box": {"answer": "UK citizens can visit visa-free."},
           "organic_results": [{"title": "Visa info", "link": "https://example.com/visa", "snippet": "No visa for short stays."}]}


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    travel_apis.clear_cache()
    for name in ("LLM_BASE_URL", "LLM_MODEL", "LLM_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SERPAPI_API_KEY", "test-key")
    yield
    travel_apis.clear_cache()


class Net:
    """Fake network. Counts calls so tests can prove that nothing was searched twice."""
    def __init__(self):
        self.serp, self.http = [], []

    def serpapi(self, params):
        self.serp.append(params["engine"])
        return {"google_flights": FLIGHTS_RAW, "google_hotels": HOTELS_RAW, "google_maps": MAPS_RAW, "google": WEB_RAW}[params["engine"]]

    def get_json(self, url, params=None):
        self.http.append(url)
        params = params or {}
        if url == travel_apis.GEOCODE_URL:
            return {"results": [{"name": params["name"], "country": "Netherlands", "latitude": 52.37, "longitude": 4.89}]}
        if url in (travel_apis.FORECAST_URL, travel_apis.ARCHIVE_URL):
            start, end = date.fromisoformat(params["start_date"]), date.fromisoformat(params["end_date"])
            days = [(start + timedelta(days=i)).isoformat() for i in range((end - start).days + 1)]
            n = len(days)
            return {"daily": {"time": days, "weather_code": [61] * n, "temperature_2m_max": [12.0] * n,
                              "temperature_2m_min": [6.0] * n, "precipitation_sum": [2.0] * n, "precipitation_probability_max": [60] * n}}
        if url.startswith("https://open.er-api.com"):
            return {"result": "success", "time_last_update_utc": "Sat, 24 Oct 2026", "rates": {"USD": 1, "EUR": 0.9, "BDT": 120.0}}
        raise AssertionError(f"unexpected URL {url}")


@pytest.fixture
def net():
    n = Net()
    with patch("agents.flight_agent.serpapi_search", n.serpapi), patch("agents.hotel_agent.serpapi_search", n.serpapi), \
         patch("utils.travel_apis.serpapi_search", n.serpapi), patch("utils.travel_apis._get_json", n.get_json):
        yield n


def ready_tools() -> TravelTools:
    t = TravelTools()
    t.call("update_trip_details", {"origin": "Madrid", "destination": "Amsterdam", "departure_date": str(D1),
                                   "return_date": str(D2), "adults": 2, "children": 1, "children_ages": [7]})
    return t


# ------------------------------------------------------------- resolver / state
def test_resolve_airport_codes_and_cities():
    assert resolve_airport("AMS")["code"] == "AMS"
    assert resolve_airport("Dhaka (DAC)")["code"] == "DAC"
    assert resolve_airport("london")["code"] == "LHR" and resolve_airport("london")["alternatives"]
    assert resolve_airport("Jessore")["code"] == "JSR"        # airport list spells the city differently
    assert resolve_airport("Nowhereville") is None and resolve_airport("") is None


def test_state_validation_keeps_old_values():
    s = TripState()
    out = s.update(origin="Madrid", destination="Amsterdam", departure_date=str(D1), return_date=str(D2), adults=2)
    assert s.origin == "MAD" and s.destination_city == "Amsterdam" and not out["rejected"] and s.nights == 7
    bad = s.update(return_date=str(D1 - timedelta(days=1)))              # return before departure
    assert "return_date" in bad["rejected"] and s.return_date == str(D2)
    assert "departure_date" in s.update(departure_date=str(TODAY - timedelta(days=1)))["rejected"]
    assert "adults" in s.update(adults=0)["rejected"] and "adults" in s.update(adults="two")["rejected"]
    assert "origin" in s.update(origin="Nowhereville")["rejected"] and s.origin == "MAD"
    assert "children_ages" in s.update(children_ages=[40])["rejected"]
    assert "return_date" in s.update(return_date="01/12/2026")["rejected"]
    assert s.update(currency="eur")["changed"]["currency"]["to"] == "EUR"


def test_state_signature_changes_only_for_relevant_fields():
    s = TripState()
    s.update(origin="MAD", destination="AMS", departure_date=str(D1), return_date=str(D2))
    before = {k: s.signature(k) for k in ("flights", "hotels", "weather", "attractions")}
    s.update(return_date=str(D2 + timedelta(days=2)))
    after = {k: s.signature(k) for k in before}
    assert [k for k in before if before[k] != after[k]] == ["flights", "hotels", "weather"]   # attractions unaffected
    s.update(currency="EUR")
    assert s.signature("weather") == after["weather"] and s.signature("flights") != after["flights"]


# ------------------------------------------------------------------- providers
def test_weather_modes(net):
    near = travel_apis.get_weather("Amsterdam", TODAY + timedelta(days=2), TODAY + timedelta(days=5), today=TODAY)
    assert near["mode"] == "forecast" and near["summary"]["days"] == 4
    far = travel_apis.get_weather("Amsterdam", D1, D2, today=TODAY)
    assert far["mode"] == "typical_from_last_year" and "NOT a forecast" in far["note"]
    assert far["daily"][0]["date"] == str(D1) and far["daily"][0]["reference_date"] == str(D1.replace(year=D1.year - 1))
    assert far["summary"]["rainy_days"] == 8 and far["daily"][0]["condition"] == "Light rain"
    past = travel_apis.get_weather("Amsterdam", TODAY - timedelta(days=10), TODAY - timedelta(days=8), today=TODAY)
    assert past["mode"] == "observed"
    with pytest.raises(ProviderError):
        travel_apis.get_weather("Amsterdam", D2, D1, today=TODAY)


def test_weather_unknown_place_is_a_clean_error():
    with patch("utils.travel_apis._get_json", return_value={}):
        with pytest.raises(ProviderError, match="Could not find"):
            travel_apis.get_weather("Zzzzzz", D1, D2)


def test_currency_conversion_fallback_and_errors(net):
    r = travel_apis.convert_currency(100, "usd", "bdt")
    assert r["converted"] == 12000.0 and r["rate"] == 120.0 and "open.er-api" in r["source"]
    assert travel_apis.convert_currency(5, "EUR", "EUR")["converted"] == 5
    with pytest.raises(ProviderError, match="3-letter"):
        travel_apis.convert_currency(1, "dollars", "EUR")
    with pytest.raises(ProviderError, match="No exchange rate"):
        travel_apis.convert_currency(1, "USD", "ZZZ")
    travel_apis.clear_cache()

    def primary_down(url, params=None):
        if url.startswith("https://open.er-api.com"):
            raise ProviderError("down")
        return {"date": "2026-10-23", "rates": {"EUR": 0.91}}
    with patch("utils.travel_apis._get_json", primary_down):
        r = travel_apis.convert_currency(100, "USD", "EUR")
    assert r["converted"] == 91.0 and "Frankfurter" in r["source"]


def test_attractions_and_web_search_parsing(net):
    a = travel_apis.find_attractions("Amsterdam", limit=2)
    assert [p["name"] for p in a["places"]] == ["Rijksmuseum", "Vondelpark"]       # best rated first, limited
    all_places = travel_apis.find_attractions("Amsterdam")["places"]
    assert all_places[-1]["name"] == "Unrated Spot" and all_places[-1]["rating"] is None
    w = travel_apis.web_search("netherlands visa uk citizens")
    assert w["quick_answer"].startswith("UK citizens") and w["results"][0]["link"] == "https://example.com/visa"
    with pytest.raises(ProviderError):
        travel_apis.web_search("  ")


# ----------------------------------------------------------------- cost maths
def test_cost_calculation_is_exact():
    t = ready_tools()
    with patch("agents.flight_agent.serpapi_search", lambda p: FLIGHTS_RAW), patch("agents.hotel_agent.serpapi_search", lambda p: HOTELS_RAW):
        t.call("search_flights"); t.call("search_hotels")
    rep = t.report()
    cost = calculate_trip_cost(rep["flights"], rep["hotels"], 7, 3, "USD", food_per_person_per_day=20, budget=1500)
    # cheapest priced flight 355 + cheapest hotel: Canal Stay 150 x 7 nights = 1050 + food 20 x 8 days x 3 people = 480
    assert [i["amount"] for i in cost["items"]] == [355.0, 1050.0, 480.0]
    assert cost["total"] == 1885.0 and cost["per_person"] == 628.33 and cost["complete"]
    assert cost["budget"] == {"amount": 1500, "status": "over budget", "difference": 385.0}
    chosen = calculate_trip_cost(rep["flights"], rep["hotels"], 7, 3, "USD", flight_option=1, hotel_option=1)
    assert chosen["total"] == 412 + 3223
    bad = calculate_trip_cost(rep["flights"], rep["hotels"], 7, 3, "USD", flight_option=99, hotel_option=2)
    assert any("does not exist" in w for w in bad["warnings"]) and any("no usable price" in w for w in bad["warnings"]) and bad["total"] is None


# ------------------------------------------------------------------ tool box
def test_tools_never_raise_and_explain_problems(net):
    t = TravelTools()
    assert "Missing trip details" in t.call("search_flights")["error"]
    assert "Unknown tool" in t.call("make_coffee")["error"]
    assert "Bad arguments" in t.call("convert_currency", {"amount": 5})["error"]
    assert "3-letter" in t.call("convert_currency", {"amount": 5, "from_currency": "xx", "to_currency": "EUR"})["error"]
    assert "Nothing to price" in t.call("calculate_trip_cost")["error"]
    assert [c.ok for c in t.trace] == [False] * 5
    upd = t.call("update_trip_details", {"origin": "Nowhereville", "color": "red"})
    assert "origin" in upd["rejected"] and "color" in upd["rejected"]


def test_provider_failure_is_reported_not_raised():
    t = ready_tools()
    def boom(params): raise ProviderError("SerpAPI rate limit or search quota reached.")
    with patch("agents.flight_agent.serpapi_search", boom):
        r = t.call("search_flights")
    assert "quota" in r["error"] and not t.trace[-1].ok


def test_search_results_cached_until_requirements_change(net):
    t = ready_tools()
    first = t.call("search_flights")
    assert first["count"] == 3 and first["cheapest_option"] == 2 and first["fastest_option"] == 1
    assert first["flights"][0]["price"] == 355 and first["flights"][-1]["price"] is None   # unpriced sorted last
    again = t.call("search_flights")
    assert net.serp.count("google_flights") == 1 and t.trace[-1].cached and again["count"] == 3
    t.call("update_trip_details", {"adults": 3})
    assert t.stale_results() == ["flights"]
    t.call("search_flights")
    assert net.serp.count("google_flights") == 2


def test_hotels_use_stay_city_and_default_child_age(net):
    t = ready_tools()
    seen = {}
    def spy(params):
        seen.update(params)
        return HOTELS_RAW
    with patch("agents.hotel_agent.serpapi_search", spy):
        t.call("update_trip_details", {"children": 2, "children_ages": [7], "stay_city": "Haarlem", "hotel_stars": "4,5"})
        r = t.call("search_hotels")
    assert seen["q"] == "hotels in Haarlem" and seen["children_ages"] == "7,8" and seen["hotel_class"] == "4,5"
    assert r["assumptions"] and r["top_rated_option"] == 1 and r["hotels"][0]["name"] == "NobleDen Hotel"


# ----------------------------------------------------------- workflow + updates
def test_workflow_runs_everything_then_reuses_then_replans_only_what_changed(net):
    t = ready_tools()
    t.call("update_trip_details", {"budget": 2000, "interests": ["museums"]})
    planner = TripPlanner(t)
    run = planner.plan(convert_total_to="EUR", food_per_person_per_day=10)
    assert sorted(run.ran) == ["attractions", "flights", "hotels", "tips", "weather"] and not run.errors
    assert run.cost["total"] == 355 + 1050 + 10 * 8 * 3 and run.cost["converted"]["currency"] == "EUR"
    assert run.cost["converted"]["total"] == round(run.cost["total"] * 0.9, 2)
    assert t.data("weather")["mode"] == "typical_from_last_year"
    calls_before = list(net.serp)
    second = planner.plan(convert_total_to="EUR")
    assert second.ran == [] and sorted(second.reused) == ["attractions", "flights", "hotels", "tips", "weather"] and net.serp == calls_before

    t.state.update(return_date=str(D2 + timedelta(days=2)))               # requirement changes
    third = planner.plan(convert_total_to="EUR")
    assert sorted(third.ran) == ["flights", "hotels", "weather"] and sorted(third.reused) == ["attractions", "tips"]
    assert net.serp.count("google_flights") == 2 and net.serp.count("google_maps") == 1
    assert [c.source for c in t.trace][-1] == "workflow"


def test_workflow_reports_missing_details_and_partial_failures(net):
    run = TripPlanner(TravelTools()).plan()
    assert set(run.skipped) == {"flights", "hotels", "weather", "attractions", "tips"} and run.cost is None
    t = ready_tools()
    def flights_fail(params):
        if params["engine"] == "google_flights": raise ProviderError("flight provider down")
        return net.serpapi(params)
    with patch("agents.flight_agent.serpapi_search", flights_fail):
        run = TripPlanner(t).plan(include_tips=False)
    assert "flights" in run.errors and "hotels" in run.ran and run.cost["includes_hotel"] and not run.cost["includes_flight"]


# ------------------------------------------------------------------ the agent
class FakeLLM:
    def __init__(self, script):
        self.script, self.calls = list(script), []
        self.chat = NS(completions=NS(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step(kwargs) if callable(step) else step


def tool_msg(*calls):
    return NS(choices=[NS(message=NS(content=None, tool_calls=[
        NS(id=f"call_{i}", function=NS(name=n, arguments=a if isinstance(a, str) else json.dumps(a))) for i, (n, a) in enumerate(calls)]))])


def text_msg(text):
    return NS(choices=[NS(message=NS(content=text, tool_calls=None))])


def make_agent(script, tools=None):
    return TravelAgent(tools or TravelTools(), client=FakeLLM(script), model="fake", today=TODAY)


def test_agent_multi_tool_turn_then_context_aware_followup(net):
    seen = {}

    def check_context(kwargs):
        seen["system"] = kwargs["messages"][0]["content"]
        return tool_msg(("update_trip_details", {"adults": 3, "return_date": str(D2 + timedelta(days=1))}))

    def after_update(kwargs):
        tool_reply = json.loads(kwargs["messages"][-1]["content"])
        seen["stale"] = tool_reply["results_now_stale"]
        seen["system2"] = kwargs["messages"][0]["content"]
        return tool_msg(("search_flights", {}), ("search_hotels", {}), ("get_weather", {}))

    agent = make_agent([
        tool_msg(("update_trip_details", {"origin": "Madrid", "destination": "Amsterdam", "departure_date": str(D1), "return_date": str(D2), "adults": 2})),
        tool_msg(("search_flights", {}), ("search_hotels", {}), ("get_weather", {})),
        tool_msg(("find_attractions", {}), ("calculate_trip_cost", {"convert_to": "EUR"})),
        text_msg("Round trip from $355; hotel from $150/night."),
        check_context,           # turn 2, round 1
        after_update,            # round 2
        text_msg("Updated for 3 adults and one more night."),
    ])
    turn = agent.chat("Plan a week in Amsterdam from Madrid for 2 adults")
    assert turn.reply.startswith("Round trip") and not turn.error and turn.rounds == 4
    assert [c.name for c in turn.calls] == ["update_trip_details", "search_flights", "search_hotels", "get_weather", "find_attractions", "calculate_trip_cost"]
    assert all(c.ok for c in turn.calls) and agent.tools.last_cost["converted"]["currency"] == "EUR"
    # every assistant tool call is answered by a tool message, in valid JSON
    ids = [tc["id"] for m in agent.history if m.get("tool_calls") for tc in m["tool_calls"]]
    answered = [m["tool_call_id"] for m in agent.history if m["role"] == "tool"]
    assert ids and ids == answered and all(json.loads(m["content"]) for m in agent.history if m["role"] == "tool")

    turn2 = agent.chat("Actually make it 3 adults and one more night")
    assert "Madrid (MAD) -> Amsterdam (AMS)" in seen["system"] and "flights: up to date" in seen["system"]    # memory reached the model
    assert sorted(seen["stale"]) == ["flights", "hotels", "weather"]                                          # attractions not stale
    assert "flights: STALE" in seen["system2"] and "attractions: up to date" in seen["system2"]
    assert agent.tools.state.adults == 3 and not agent.tools.stale_results() and turn2.reply.startswith("Updated")
    assert [c.name for c in turn2.calls] == ["update_trip_details", "search_flights", "search_hotels", "get_weather"]
    assert len(agent.history) > 4                                                                             # conversation history kept


def test_agent_recovers_from_tool_errors_and_bad_json(net):
    seen = []
    def after_errors(kwargs):
        seen.extend(json.loads(m["content"]) for m in kwargs["messages"] if m["role"] == "tool")
        return text_msg("Where are you flying from, and on which dates?")
    agent = make_agent([tool_msg(("search_flights", {}), ("get_weather", "{not json")), after_errors])
    turn = agent.chat("find me flights")
    assert turn.reply.startswith("Where are you") and [c.ok for c in turn.calls] == [False]
    assert "Missing trip details" in seen[0]["error"] and "not valid JSON" in seen[1]["error"]


def test_agent_stops_after_max_rounds(net):
    script = [tool_msg(("convert_currency", {"amount": 1, "from_currency": "USD", "to_currency": "EUR"}))] * MAX_TOOL_ROUNDS + [text_msg("Best I can do.")]
    agent = make_agent(script)
    turn = agent.chat("loop forever")
    assert turn.reply == "Best I can do." and turn.rounds == MAX_TOOL_ROUNDS
    assert "tools" not in agent._llm_client.calls[-1]                  # the final "answer now" call offers no tools
    assert len(agent._llm_client.calls) == MAX_TOOL_ROUNDS + 1


def test_agent_model_failure_leaves_clean_history():
    agent = make_agent([tool_msg(("convert_currency", {"amount": 1, "from_currency": "USD", "to_currency": "EUR"})), RuntimeError("401 bad key")])
    with patch("utils.travel_apis._get_json", Net().get_json):
        turn = agent.chat("convert please")
    assert turn.error and "could not answer" in turn.error and agent.history == []
    assert TravelAgent().chat("hello").error and "No AI model" in TravelAgent().chat("hello").error


def test_agent_history_is_trimmed_at_user_messages():
    agent = make_agent([text_msg("ok")])
    agent.history = [{"role": "user", "content": "u"}, {"role": "assistant", "content": "", "tool_calls": [{"id": "x", "type": "function", "function": {"name": "a", "arguments": "{}"}}]},
                     {"role": "tool", "tool_call_id": "x", "content": "{}"}] * 20
    agent._trim_history()
    assert agent.history[0]["role"] == "user" and len(agent.history) <= 40


def test_traditional_chatbot_has_no_tools():
    llm = FakeLLM([text_msg("I can't see live prices, but flights are usually cheaper midweek.")])
    reply = TraditionalChatbot(client=llm, model="fake").reply("How much is a flight?")
    assert "live prices" in reply and "tools" not in llm.calls[0] and "NO tools" in llm.calls[0]["messages"][0]["content"]
    with pytest.raises(LLMUnavailableError):
        TraditionalChatbot().reply("hi")


# ------------------------------------------------------------------ the page
def test_agent_page_loads_without_llm_and_workflow_runs(net):
    from streamlit.testing.v1 import AppTest
    from utils.validation import airport_label
    at = AppTest.from_file(MAIN_PAGE, default_timeout=60).run()
    assert not at.exception
    assert any("AI model: not configured" in m.value for m in at.sidebar.markdown)
    assert at.chat_input[0].disabled                                  # no LLM -> chat is disabled, the workflow still works
    at.selectbox(key="ag_origin").select(airport_label("MAD"))
    at.selectbox(key="ag_destination").select(airport_label("AMS"))
    at.button(key="ag_plan").click().run()
    assert not at.exception and not at.error
    ctx = at.session_state["agent_ctx"]
    assert ctx["tools"].state.destination == "AMS" and ctx["last_run"].cost and not ctx["last_run"].errors
    assert ctx["tools"].data("weather") and ctx["tools"].data("hotels")
    # change a requirement from the page: only affected searches run again
    before = list(net.serp)
    at.number_input(key="chg_adults").set_value(2)
    at.button(key="chg_apply").click().run()
    assert not at.exception
    ctx = at.session_state["agent_ctx"]
    assert sorted(ctx["change_log"]["ran"]) == ["flights", "hotels"] and "attractions" in ctx["change_log"]["reused"]
    assert net.serp[len(before):].count("google_maps") == 0


def test_agent_page_rejects_missing_airports(net):
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(MAIN_PAGE, default_timeout=60).run()
    at.button(key="ag_plan").click().run()
    assert at.error and not at.session_state["agent_ctx"]["tools"].results


def _configured_page(monkeypatch, script):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv("LLM_BASE_URL", "http://fake.invalid/v1")
    monkeypatch.setenv("LLM_MODEL", "fake-model")
    llm = FakeLLM(script)
    patcher = patch("agents.base_agent.BaseAgent._get_llm_client", lambda self: llm)
    patcher.start()
    return AppTest.from_file(MAIN_PAGE, default_timeout=60), llm, patcher


def test_agent_page_chat_shows_reply_and_tool_calls(net, monkeypatch):
    at, llm, patcher = _configured_page(monkeypatch, [
        tool_msg(("convert_currency", {"amount": 355, "from_currency": "USD", "to_currency": "BDT"})),
        text_msg("The flight costs $355, about 42,600 BDT."),
    ])
    try:
        at.run()
        assert not at.chat_input[0].disabled
        at.chat_input[0].set_value("How much is 355 USD in BDT?").run()
        assert not at.exception
        roles = [m.name for m in at.chat_message]
        assert roles == ["user", "assistant"]
        text = " ".join(m.value for m in at.chat_message[1].markdown)
        assert "\\$355" in text                                      # $ escaped so Streamlit does not render LaTeX
        assert any("1 tool call" in e.label for e in at.chat_message[1].expander)
        assert at.session_state["agent_ctx"]["tools"].trace[0].name == "convert_currency"
    finally:
        patcher.stop()


def test_agent_page_compare_tab_runs_both(net, monkeypatch):
    at, llm, patcher = _configured_page(monkeypatch, [
        text_msg("Typically around a few hundred dollars; I can't see live prices."),     # chatbot
        text_msg("Cheapest flight is $355."),                                              # agent (no tools needed in this script)
    ])
    try:
        at.run()
        at.button(key="cmp_go").click().run()
        assert not at.exception
        cmp = at.session_state["agent_ctx"]["compare"]
        assert "live prices" in cmp["chatbot"] and cmp["agent"].startswith("Cheapest")
        assert "tools" not in llm.calls[0] and "tools" in llm.calls[1]      # the ONLY difference: the agent is offered tools
    finally:
        patcher.stop()
