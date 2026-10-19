"""Page styling (one CSS block). Palette: deep navy + teal, light grey background.

Change the colours in one place: the :root variables below (and .streamlit/config.toml).
"""

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

:root {
  --navy: #0F2A43;
  --navy-2: #173B5C;
  --teal: #0E8F9C;
  --teal-dark: #0A6F7A;
  --teal-tint: #E3F4F6;
  --bg: #F5F7FA;
  --line: #E2E8F0;
  --muted: #64748B;
  --shadow: 0 1px 3px rgba(15, 42, 67, .08), 0 4px 14px rgba(15, 42, 67, .06);
}

html, body, [class*="css"], .stApp { font-family: 'Inter', 'Segoe UI', system-ui, sans-serif; }
.block-container { padding-top: 1.2rem; max-width: 1280px; }
#MainMenu, footer { visibility: hidden; }
h1, h2, h3, h4 { color: var(--navy); letter-spacing: -.01em; }

/* ---------- hero */
.hero {
  position: relative; overflow: hidden; color: #fff; border-radius: 16px;
  padding: 30px 36px; margin-bottom: 20px;
  background:
    radial-gradient(circle at 88% 20%, rgba(14, 143, 156, .55), transparent 45%),
    linear-gradient(135deg, var(--navy) 0%, var(--navy-2) 100%);
  box-shadow: 0 12px 30px rgba(15, 42, 67, .25);
}
.hero h1 { color: #fff; margin: 0; padding: 0; font-size: 2rem; font-weight: 800; letter-spacing: -.02em; }
.hero p { margin: 8px 0 0; color: #CBD9E6; font-size: 1rem; max-width: 640px; }
.hero .chips span {
  display: inline-block; margin: 14px 8px 0 0; padding: 4px 14px; border-radius: 999px;
  font-size: .78rem; font-weight: 600; letter-spacing: .02em;
  color: #D7EEF1; background: rgba(255, 255, 255, .09); border: 1px solid rgba(255, 255, 255, .18);
}

/* ---------- cards */
[class*="st-key-card"] {
  background: #fff; border-radius: 12px; border-left: 4px solid var(--teal);
  box-shadow: var(--shadow); transition: box-shadow .15s ease, transform .15s ease;
}
[class*="st-key-card"]:hover { box-shadow: 0 2px 4px rgba(15,42,67,.08), 0 10px 24px rgba(15,42,67,.12); }
.st-key-card_form { border-left-color: var(--navy); padding-bottom: .4rem; }

/* ---------- metric tiles */
[data-testid="stMetric"] {
  background: #fff; border: 1px solid var(--line); border-top: 3px solid var(--teal);
  border-radius: 12px; padding: 14px 16px; box-shadow: var(--shadow);
}
[data-testid="stMetricLabel"] p { color: var(--muted); font-weight: 600; font-size: .78rem; text-transform: uppercase; letter-spacing: .05em; }
[data-testid="stMetricValue"] { color: var(--navy); font-weight: 800; }

/* ---------- inputs & buttons */
[data-baseweb="select"] > div, [data-baseweb="input"] > div, [data-testid="stDateInput"] > div > div { border-radius: 10px; }
.stButton > button[kind="primary"] {
  background: linear-gradient(135deg, var(--teal), var(--teal-dark)); color: #fff; border: 0;
  border-radius: 10px; font-weight: 700; padding: .55rem 1.5rem; box-shadow: 0 4px 12px rgba(14, 143, 156, .35);
}
.stButton > button[kind="primary"]:hover { filter: brightness(1.06); }
.stButton > button:not([kind="primary"]), .stDownloadButton > button {
  border-radius: 10px; font-weight: 600; border: 1px solid var(--line); color: var(--navy); background: #fff;
}
.stDownloadButton > button:hover, .stButton > button:not([kind="primary"]):hover { border-color: var(--teal); color: var(--teal-dark); }

/* ---------- tabs, expanders */
[data-testid="stTabs"] button { font-weight: 700; font-size: .98rem; color: var(--muted); }
[data-testid="stTabs"] button[aria-selected="true"] { color: var(--navy); }
[data-testid="stExpander"] { border-radius: 12px; border: 1px solid var(--line); background: #fff; }
hr { border-color: var(--line); }

/* ---------- route heading, pills, placeholders */
.route-title { font-size: 1.55rem; font-weight: 800; color: var(--navy); margin: 4px 0 2px; letter-spacing: -.01em; }
.pill {
  display: inline-block; margin: 4px 8px 4px 0; padding: 4px 12px; border-radius: 999px;
  background: var(--teal-tint); color: var(--teal-dark); font-size: .8rem; font-weight: 600;
}
.photo-ph {
  height: 120px; display: flex; flex-direction: column; align-items: center; justify-content: center;
  border-radius: 12px; font-weight: 800; font-size: 1.8rem; color: var(--navy);
  background: linear-gradient(135deg, #E8EEF4, #D5E0EA);
}
.photo-ph small { font-weight: 500; font-size: .75rem; color: var(--muted); }
</style>
"""

HERO = """
<div class="hero">
  <h1>✈️ AI Travel Analysis</h1>
  <p>Search flights and hotels, compare and filter the options, then download a professional report.</p>
  <div class="chips"><span>Flights</span><span>Hotels</span><span>Smart filters</span><span>PDF · Excel · CSV · JSON · Word</span></div>
</div>
"""
