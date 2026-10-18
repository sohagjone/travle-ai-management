"""Page styling (one CSS block). Kept separate so the look is easy to tweak."""

CSS = """
<style>
.block-container { padding-top: 1.4rem; max-width: 1280px; }
#MainMenu, footer { visibility: hidden; }

.hero {
  background: linear-gradient(120deg, #0B3C8C 0%, #1F6FEB 55%, #35A7FF 100%);
  color: #fff; padding: 26px 32px; border-radius: 18px; margin-bottom: 18px;
  box-shadow: 0 10px 28px rgba(31, 111, 235, .28);
}
.hero h1 { color: #fff; margin: 0; padding: 0; font-size: 2.1rem; letter-spacing: -.5px; }
.hero p { margin: 6px 0 0; opacity: .93; font-size: 1.02rem; }
.hero .chips span {
  display: inline-block; background: rgba(255,255,255,.18); border-radius: 999px;
  padding: 3px 13px; margin: 12px 8px 0 0; font-size: .8rem; font-weight: 600;
}

[class*="st-key-card"] {
  background: #fff; border-radius: 14px; box-shadow: 0 2px 10px rgba(20, 33, 61, .07);
  transition: box-shadow .15s ease;
}
[class*="st-key-card"]:hover { box-shadow: 0 8px 22px rgba(20, 33, 61, .13); }

[data-testid="stMetric"] {
  background: #fff; border: 1px solid #E3EAF4; border-radius: 14px; padding: 14px 16px;
  box-shadow: 0 2px 10px rgba(20, 33, 61, .06);
}
[data-testid="stMetricValue"] { color: #0B3C8C; font-weight: 700; }

.stButton > button[kind="primary"] {
  background: linear-gradient(120deg, #1F6FEB, #0B5FFF); border: 0; border-radius: 10px;
  font-weight: 700; padding: .55rem 1.4rem; box-shadow: 0 4px 12px rgba(31, 111, 235, .35);
}
.stButton > button, .stDownloadButton > button { border-radius: 10px; font-weight: 600; }
[data-testid="stTabs"] button { font-weight: 700; font-size: 1rem; }
h2, h3 { color: #14213D; }
.route-title { font-size: 1.6rem; font-weight: 800; color: #0B3C8C; margin: 4px 0 2px; }
.pill {
  display: inline-block; background: #EAF1FD; color: #0B3C8C; border-radius: 999px;
  padding: 3px 12px; margin: 4px 8px 4px 0; font-size: .82rem; font-weight: 600;
}
.photo-ph {
  background: linear-gradient(135deg, #EAF1FD, #D6E4FB); color: #0B3C8C; border-radius: 12px;
  height: 120px; display: flex; flex-direction: column; align-items: center; justify-content: center;
  font-weight: 800; font-size: 1.8rem;
}
.photo-ph small { font-weight: 500; font-size: .75rem; opacity: .75; }
</style>
"""

HERO = """
<div class="hero">
  <h1>✈️ AI Travel Analysis</h1>
  <p>Search flights and hotels, compare and filter the options, then download your report.</p>
  <div class="chips"><span>Flights</span><span>Hotels</span><span>Smart filters</span><span>PDF · Excel · CSV · JSON · Word</span></div>
</div>
"""
