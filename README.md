# AI Travel Analysis

Streamlit app that plans a whole trip: flights, hotels, tourist attractions, weather, trip cost, currency conversion, a day-by-day plan, follow-up questions, and downloads (PDF, Excel, Word, CSV, JSON).

## Run locally
```bash
python -m venv venv
venv\Scripts\activate          # Windows (macOS/Linux: source venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env         # then edit .env and add SERPAPI_API_KEY
streamlit run main.py
```
Tests (all external services are mocked): `pip install -r requirements-dev.txt` then `python -m pytest -q`

## Where the data comes from
| Feature | Source | Key needed | Cost |
|---|---|---|---|
| Flights, hotels | SerpAPI (Google Flights / Hotels) | `SERPAPI_API_KEY` | 1 SerpAPI search each |
| Tourist attractions | SerpAPI (Google Maps) | same key | 1 SerpAPI search |
| Airport photos | Wikipedia first, then SerpAPI Google Images | same key | 0 to 1 search per airport (cached) |
| Weather | Open-Meteo (forecast up to ~15 days, otherwise typical weather from the last 3 years) | none | free |
| Currency rates | open.er-api.com, fallback Frankfurter (ECB) | none | free |

So one trip search uses **3 SerpAPI searches** (plus up to 2 for airport photos if Wikipedia cannot be reached).

## Configuration (env vars or Streamlit secrets)
| Name | Needed for |
|---|---|
| `SERPAPI_API_KEY` | **Required** |
| `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY` | Optional: AI recommendations and free-form follow-up answers (any OpenAI-compatible API). Without them, rules answer the common questions. |
| `SENDGRID_KEY`, `SENDGRID_FROM_EMAIL` | Optional: "Email these results" |

## Deploy on Streamlit Cloud
1. Copy ALL files into your repo (new folders: `views/`, `assets/`), then `git add . && git commit -m "Update" && git push`
2. Settings -> Secrets: values like `.streamlit/secrets.toml.example`
3. Reboot the app. Never commit `.env` or `secrets.toml`.

## Structure
`main.py` page flow and search · `views/` one file per result tab (plan, attractions, weather, cost, assistant) · `agents/` flights, hotels, attractions, weather, currency, assistant, email, orchestrator · `utils/` report model, trip cost, trip plan, exports (PDF/Excel/Word/CSV/JSON), validation, styles · `tests/`
