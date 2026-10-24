# AI Travel Analysis

Streamlit app: search flights + hotels (SerpAPI), filter/compare them, see origin/destination airport photos (from Wikipedia, with a placeholder when none is found), and **download the results** as PDF, Excel, Word, CSV (flights / hotels) and JSON.

**New: AI Travel Agent page** (sidebar > *AI Travel Agent*). An AI agent that uses tools to plan a whole trip: flights, hotels, tourist attractions, weather, web search, trip cost, currency conversion - with a trip memory, follow-up questions and smart re-planning when requirements change. See [AI Travel Agent](#ai-travel-agent) below.

## Run locally
```bash
python -m venv venv
venv\Scripts\activate          # Windows (macOS/Linux: source venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env         # then edit .env and add SERPAPI_API_KEY
streamlit run main.py
```
Run the tests (all provider calls are mocked): `pip install -r requirements-dev.txt` then `python -m pytest -q`

## Configuration (env vars or Streamlit secrets)
| Name | Needed for |
|---|---|
| `SERPAPI_API_KEY` | **Required** - flights and hotels |
| `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY` | Optional - AI recommendations (any OpenAI-compatible API). Without them a rule-based summary is used. **The chat agent needs a model that supports tool calling** (e.g. `gpt-4o-mini`, or `llama3.2` / `qwen2.5` on Ollama). Local Ollama: `http://localhost:11434/v1`, `llama3.2`, `ollama` |
| `SENDGRID_KEY`, `SENDGRID_FROM_EMAIL` | Optional - "Email these results" |

## AI Travel Agent

| Tab | What it shows |
|---|---|
| **Chat agent** | An AI agent with tools. It remembers the trip, so follow-ups work: *"what's the weather there?"*, *"make it 3 adults"*, *"show the total in EUR"*. Under each answer, **tool calls** lists exactly what it looked up. Needs an AI model. |
| **Plan a trip (workflow)** | The complete planning workflow **without an AI model**: flights, hotels, weather, attractions and tips run in parallel, then the cost and currency conversion. In the **Cost** tab you can price any flight and hotel option instead of the cheapest (arithmetic only, no new search). **Change a requirement** afterwards (cities, stay city, dates, travellers, rooms, stars, interests, stops, currency, budget) and only the affected searches run again. Results can be downloaded (PDF/Excel/Word/JSON). |
| **Agent vs chatbot** | A comparison table, and a live test that sends the same question to a plain chatbot (no tools) and to the agent. |
| **How the tools work together** | A diagram, the tool list, a worked example and a live trace of every tool call. |

**Tools** (`utils/travel_tools.py`)

| Tool | Purpose | Data source | Key |
|---|---|---|---|
| `update_trip_details` | Remember / change requirements | trip memory | - |
| `search_flights` | Flight options and prices | SerpAPI Google Flights | `SERPAPI_API_KEY` |
| `search_hotels` | Hotels and accommodation | SerpAPI Google Hotels | `SERPAPI_API_KEY` |
| `find_attractions` | Tourist attractions | SerpAPI Google Maps | `SERPAPI_API_KEY` |
| `get_weather` | Forecast (next ~2 weeks) or typical weather from the same dates last year | Open-Meteo | none |
| `web_search` | Visas, events, tips, anything else | SerpAPI Google Search | `SERPAPI_API_KEY` |
| `convert_currency` | Live exchange rates | open.er-api.com (backup: Frankfurter) | none |
| `calculate_trip_cost` | Exact cost sum + budget check | latest flight/hotel results | none |

**How it works**
* `utils/trip_state.py` - the **trip memory**. Every tool reads it; `update()` validates changes and keeps the old value when a change is invalid.
* **Stale tracking** - each result remembers the trip fields it was searched with. Change the return date and flights, hotels and weather become stale; attractions do not. Cached results are reused, so no search is repeated needlessly.
* **Sensible changes** - changing the destination also resets a stay city that belonged to the old destination (otherwise hotels, weather and attractions would be searched in the wrong place). Moving only the departure date past the old return date keeps the trip length and shifts the return date; an explicitly impossible return date is refused and the old dates are kept.
* The **Change a requirement** panel always starts from the current trip, even if the chat agent changed it a moment ago, so pressing Apply never undoes that change.
* `agents/travel_agent.py` - the agent loop (think, call tools, read results, repeat; max 8 rounds). The system prompt is rebuilt every turn with the current trip and which results are stale. Independent tools run in parallel; a trip change always runs first.
* `agents/trip_planner.py` - the fixed workflow, built on the same tools.
* Tools never raise: a problem comes back as `{"error": ...}` so the model can fix the input or ask the person.
* The AI model never does arithmetic or currency maths - `calculate_trip_cost` and `convert_currency` do.

**Good to know**
* Weather beyond about 16 days is **not a forecast**: the page and the agent say so and show last year's weather for the same dates.
* Flight prices are shown as the provider returns them; confirm on the booking page whether they are per person.
* A full workflow run uses up to 4 SerpAPI searches (flights, hotels, attractions, and one for tips; more if you pick several interests). The chat agent uses what it needs.

## Deploy on Streamlit Cloud
1. `git add . && git commit -m "Add downloads, fixes" && git push`
2. Streamlit Cloud -> your app -> Settings -> Secrets: paste values like `.streamlit/secrets.toml.example`.
3. Reboot the app. Never commit `.env` or `secrets.toml`.

## Structure
`main.py` UI · `pages/1_AI_Travel_Agent.py` agent UI · `agents/` search + email agents + `travel_agent.py` (agent, chatbot) + `trip_planner.py` (workflow) · `utils/travel_tools.py` tools · `utils/trip_state.py` trip memory · `utils/travel_apis.py` weather/currency/places/web · `utils/trip_costs.py` cost maths · `utils/airport_resolver.py` · `utils/report_data.py` single report model · `utils/pdf_generator.py`, `excel_generator.py`, `docx_generator.py`, `export_reports.py` (CSV/JSON + one entry point) · `assets/fonts` DejaVu (Unicode PDF text) · `tests/`
