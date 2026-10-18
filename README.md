# AI Travel Analysis

Streamlit app: search flights + hotels (SerpAPI), filter/compare them, see origin/destination airport photos (from Wikipedia, with a placeholder when none is found), and **download the results** as PDF, Excel, Word, CSV (flights / hotels) and JSON.

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
| `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY` | Optional - AI recommendations (any OpenAI-compatible API). Without them a rule-based summary is used. Local Ollama: `http://localhost:11434/v1`, `llama3.2`, `ollama` |
| `SENDGRID_KEY`, `SENDGRID_FROM_EMAIL` | Optional - "Email these results" |

## Deploy on Streamlit Cloud
1. `git add . && git commit -m "Add downloads, fixes" && git push`
2. Streamlit Cloud -> your app -> Settings -> Secrets: paste values like `.streamlit/secrets.toml.example`.
3. Reboot the app. Never commit `.env` or `secrets.toml`.

## Structure
`main.py` UI · `agents/` search + email agents · `utils/report_data.py` single report model · `utils/pdf_generator.py`, `excel_generator.py`, `docx_generator.py`, `export_reports.py` (CSV/JSON + one entry point) · `assets/fonts` DejaVu (Unicode PDF text) · `tests/`
