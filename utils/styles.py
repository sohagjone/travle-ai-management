"""Page styling (one CSS block). Palette: deep navy + teal, light grey background.

Change the colours in one place: the :root variables below (and .streamlit/config.toml).
"""

import random
from urllib.parse import quote


def _landscape_svg() -> str:
    """Original illustration (sky, clouds, mountains, pine forest) drawn in code: no image files or hotlinks."""
    rnd = random.Random(7)
    trees = []
    for i in range(70):
        x = rnd.randint(-20, 1620)
        base = rnd.randint(655, 705)
        h = rnd.randint(46, 96)
        w = h * 0.42
        shade = rnd.choice(["#1C4A2A", "#20532F", "#173F24"])
        for k in range(3):
            top = base - h + k * h * 0.26
            half = w * (0.55 + k * 0.22)
            trees.append(
                f'<polygon points="{x},{top:.0f} {x - half:.0f},{top + h * 0.42:.0f} {x + half:.0f},{top + h * 0.42:.0f}" fill="{shade}"/>'
            )
        trees.append(f'<rect x="{x - 2}" y="{base - h * 0.08:.0f}" width="4" height="{h * 0.1:.0f}" fill="#3B2A1A"/>')
    snow = (
        '<polygon points="440,262 470,226 506,266 488,258 470,272 452,258" fill="#fff" opacity=".85"/>'
        '<polygon points="1168,268 1200,232 1236,270 1218,262 1200,276 1184,262" fill="#fff" opacity=".85"/>'
        '<polygon points="796,282 822,248 852,284 836,277 822,288 808,277" fill="#fff" opacity=".8"/>'
    )
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1600 720" preserveAspectRatio="xMidYMax slice">'
        '<defs>'
        '<linearGradient id="sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#4A8EC6"/>'
        '<stop offset=".55" stop-color="#7DB8E2"/><stop offset="1" stop-color="#BFE0F3"/></linearGradient>'
        '<linearGradient id="mid" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#5E9F6B"/>'
        '<stop offset="1" stop-color="#3C7A49"/></linearGradient>'
        '<filter id="blur"><feGaussianBlur stdDeviation="16"/></filter></defs>'
        '<rect width="1600" height="720" fill="url(#sky)"/>'
        '<g fill="#fff" opacity=".9" filter="url(#blur)">'
        '<ellipse cx="260" cy="150" rx="150" ry="38"/><ellipse cx="340" cy="128" rx="100" ry="34"/>'
        '<ellipse cx="1260" cy="120" rx="170" ry="40"/><ellipse cx="1160" cy="140" rx="110" ry="32"/>'
        '<ellipse cx="720" cy="86" rx="120" ry="26"/></g>'
        '<path d="M0 430 L180 300 L300 360 L470 226 L640 340 L822 248 L1000 360 L1200 232 L1400 330 L1600 270 L1600 720 L0 720Z" fill="#7C9FBA" opacity=".85"/>'
        + snow +
        '<path d="M0 530 L160 430 L330 505 L520 400 L720 505 L930 410 L1150 505 L1350 420 L1600 515 L1600 720 L0 720Z" fill="url(#mid)"/>'
        '<path d="M0 610 Q300 530 600 600 T1200 590 T1600 570 L1600 720 L0 720Z" fill="#2E6B3B"/>'
        + "".join(trees) +
        '</svg>'
    )


BG_URI = "data:image/svg+xml;utf8," + quote(_landscape_svg(), safe="/:=,; ")

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

:root {
  --navy: #0F2A43; --teal: #0E8F9C; --teal-dark: #0A6F7A; --teal-tint: #E3F4F6;
  --orange: #FF8A00; --orange-dark: #F26B00;
  --bg: #F5F7FA; --line: #E2E8F0; --muted: #64748B;
  --shadow: 0 1px 3px rgba(15, 42, 67, .08), 0 4px 14px rgba(15, 42, 67, .06);
}

html, body, [class*="css"], .stApp { font-family: 'Inter', 'Segoe UI', system-ui, sans-serif; }
html, body, .stApp, [data-testid="stMain"], [data-testid="stAppViewContainer"] { overflow-x: hidden; }
header[data-testid="stHeader"] { background: transparent; }
.block-container { padding-top: 0; max-width: 1180px; }
#MainMenu, footer { visibility: hidden; }
h1, h2, h3, h4 { color: var(--navy); letter-spacing: -.01em; }

/* ---------- full-width hero with illustrated landscape */
.hero {
  width: 100vw; margin-left: calc(50% - 50vw); box-sizing: border-box;
  padding: 18px 6vw 190px; color: #fff; text-align: center;
  background-image: url("__BG__"); background-size: cover; background-position: center bottom;
}
.hero .nav { text-align: left; padding-bottom: 6px; }
.hero .brand { display: inline-block; font-size: 1.45rem; font-weight: 800; letter-spacing: -.02em; vertical-align: middle; }
.hero .logo {
  display: inline-block; width: 38px; height: 38px; line-height: 38px; margin-right: 10px; text-align: center;
  border-radius: 50%; background: #2F4CF0; font-size: 1.1rem; vertical-align: middle;
}
.hero .links { display: inline-block; margin-left: 56px; vertical-align: middle; }
.hero .links span { display: inline-block; margin-right: 30px; font-weight: 600; font-size: 1rem; opacity: .72; }
.hero .links span.active { opacity: 1; }
.hero h1 {
  margin: 34px 0 0; padding: 0; font-size: 3.4rem; line-height: 1.1; font-weight: 800; letter-spacing: -.03em;
  color: #9DF5E4;
  background: linear-gradient(90deg, #86F7DE 0%, #B7DCFF 50%, #F6B8F3 100%);
  -webkit-background-clip: text; background-clip: text; -webkit-text-fill-color: transparent;
  filter: drop-shadow(0 2px 6px rgba(15, 42, 67, .25));
}
.hero p { margin: 18px auto 0; max-width: 760px; font-size: 1.2rem; font-weight: 600; color: #fff; text-shadow: 0 1px 8px rgba(15, 42, 67, .45); }

/* ---------- the search card floats over the hero, like a big search box */
.st-key-card_form {
  position: relative; z-index: 3; margin-top: -150px; padding: 1.1rem 1.5rem .8rem;
  background: linear-gradient(#fff, #fff) padding-box, linear-gradient(90deg, #7FF3DA, #F4B2F2) border-box;
  border: 2px solid transparent; border-radius: 22px; box-shadow: 0 18px 44px rgba(15, 42, 67, .22);
}
.st-key-card_form label p { font-weight: 700; color: var(--navy); font-size: .85rem; }

/* ---------- feature pills under the card */
.chips-row { text-align: center; margin: 14px 0 6px; }
.chips-row span {
  display: inline-block; margin: 6px 6px; padding: 10px 22px; border-radius: 999px; background: #fff;
  color: var(--navy); font-weight: 600; font-size: .95rem; box-shadow: var(--shadow);
}

/* ---------- result cards */
[class*="st-key-card_flight"], [class*="st-key-card_hotel"] {
  background: #fff; border-radius: 14px; border-left: 4px solid var(--teal);
  box-shadow: var(--shadow); transition: box-shadow .15s ease;
}
[class*="st-key-card_flight"]:hover, [class*="st-key-card_hotel"]:hover { box-shadow: 0 2px 4px rgba(15,42,67,.08), 0 10px 24px rgba(15,42,67,.12); }

[data-testid="stMetric"] {
  background: #fff; border: 1px solid var(--line); border-top: 3px solid var(--teal);
  border-radius: 14px; padding: 14px 16px; box-shadow: var(--shadow);
}
[data-testid="stMetricLabel"] p { color: var(--muted); font-weight: 600; font-size: .78rem; text-transform: uppercase; letter-spacing: .05em; }
[data-testid="stMetricValue"] { color: var(--navy); font-weight: 800; }

/* ---------- inputs & buttons */
[data-baseweb="select"] > div, [data-baseweb="input"] > div, [data-testid="stDateInput"] > div > div { border-radius: 12px; }
.stButton > button[kind="primary"] {
  background: linear-gradient(135deg, var(--orange), var(--orange-dark)); color: #fff; border: 0;
  border-radius: 12px; font-weight: 700; padding: .6rem 1.6rem; box-shadow: 0 6px 16px rgba(255, 122, 0, .35);
}
.stButton > button[kind="primary"]:hover { filter: brightness(1.06); }
.stButton > button:not([kind="primary"]), .stDownloadButton > button {
  border-radius: 12px; font-weight: 600; border: 1px solid var(--line); color: var(--navy); background: #fff;
}
.stDownloadButton > button:hover, .stButton > button:not([kind="primary"]):hover { border-color: var(--teal); color: var(--teal-dark); }

[data-testid="stTabs"] button { font-weight: 700; font-size: .98rem; color: var(--muted); }
[data-testid="stTabs"] button[aria-selected="true"] { color: var(--navy); }
[data-testid="stExpander"] { border-radius: 14px; border: 1px solid var(--line); background: #fff; }
hr { border-color: var(--line); }

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

@media (max-width: 800px) {
  .hero { padding-bottom: 170px; }
  .hero .links { display: none; }
  .hero h1 { font-size: 2.1rem; margin-top: 24px; }
  .hero p { font-size: 1rem; }
  .st-key-card_form { margin-top: -130px; padding: .8rem 1rem; }
}
</style>
""".replace("__BG__", BG_URI)

HERO = """
<div class="hero">
  <div class="nav">
    <span class="brand"><span class="logo">✈</span>AI Travel Analysis</span>
    <span class="links"><span class="active">Trip Planner</span><span>Flights</span><span>Hotels</span><span>Reports</span></span>
  </div>
  <h1>Find your perfect trip, faster.</h1>
  <p>Compare flights and hotels, filter instantly, and download a ready-to-share report.</p>
</div>
"""

FEATURE_CHIPS = """
<div class="chips-row">
  <span>✈️ Compare flights</span><span>🏨 Compare hotels</span><span>🔎 Filter instantly</span><span>📄 Download reports</span>
</div>
"""
