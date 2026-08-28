"""
Vantage Screener — Methodology page.

Scoped deliberately narrow: what a visitor needs to understand the
numbers on screen — the Composite Upside % formula and a glossary of
terms — not a build log. Development history, what got tried and
dropped, and internal implementation details live in this repo's
DESIGN_DOC.md instead, for anyone reading the code rather than using
the site.
"""

import streamlit as st

from theme import APP_NAME, inject_theme_css

# Each file under pages/ is its own independent Streamlit script — the
# CSS injected in app.py does NOT carry over here, so this page needs
# its own set_page_config()/inject_theme_css() call, same as app.py.
st.set_page_config(page_title=f"{APP_NAME} — Methodology", page_icon="📖", layout="centered")
inject_theme_css()

# Back-link FIRST, above the title. With the sidebar nav hidden
# (.streamlit/config.toml), this is the only way back to the app, so it
# should be visible without scrolling to the bottom of a long page.
st.page_link("app.py", label="← Back to Vantage Screener")

st.title("Methodology")

st.markdown(f"""
{APP_NAME} screens stocks against one published set of rules and
shows whichever ones currently match — a heatmap and a list, both
driven by the same score: **Composite Upside %**.

### Composite Upside % — the score everything is sorted by

A weighted blend of three "how much room is left to grow" measures, all
expressed the same way analysts normally quote upside (as a % of
today's price). The weights are yours to change — the "Weights used to
compute Composite Upside%" slider on the main screener re-runs this
same formula with whatever split you set. The table below shows the
defaults it opens with:

| Component | Default weight | What it measures |
|---|---|---|
| Upside to the moving average | **50%** | Has the price genuinely pulled back recently, not just noise |
| Upside to the 52-week high | 25% | Distance from the highest point in the past year |
| Upside to the analyst median target | 25% | Distance from where analysts expect the price to go |

`Composite Upside % = w1×(upside to moving avg) + w2×(upside to 52w high) + w3×(upside to target)` — at the defaults, `w1=0.50, w2=0.25, w3=0.25`

The moving average carries the largest weight *by default* because a
52-week high is a single day and can be touched briefly without meaning
much — a sustained move below the moving average is a stronger signal
that a stock has genuinely, recently pulled back. Analyst targets carry
a well-documented optimism bias in practice, so that component defaults
to equal weight with (not above) the 52-week high rather than trusted
most. Disagree with that reasoning? Drag the slider and see a different
set of stocks rise to the top.

A stock must also clear the market-cap range and the maximum analyst
rating set in the filter panel to appear at all — Composite Upside % is
the ranking score, not the only bar to clear.

### Glossary

**Analyst rating (1–5 scale)** — Yahoo's aggregate of every covering
analyst's call. **1.0 = Strong Buy, 5.0 = Strong Sell** — lower is more
bullish, easy to get backwards since a *higher* number is *worse*.

**Market cap** — share price × total shares outstanding, roughly a
company's total value. Large / Mid / Small Cap tags on each card are a
separate display-only classification, not tied to the market-cap range
filter.

**Moving average** — the average closing price over the last 50 or 200
trading days, a standard way to see a stock's typical recent price
without day-to-day noise.

**52-week range** — the highest and lowest closing price over the past
year, and where today's price sits between them. Shown as a bar on each
card with "% above low" — a measure of distance already travelled, kept
separate from the three upside figures above (which measure room still
left to gain).

**Composite Upside %** — see the formula above.

### Data source

Prices, analyst targets, and recommendation counts come from **Yahoo
Finance**, via the free, unofficial `yfinance` Python library — not
guaranteed accurate, complete, or continuously available.
""")

# A real st.page_link, not a markdown [link](Disclaimer) — a plain
# anchor forces a full browser reload, which starts a new session and
# would silently reset the URL-persisted filters (see the URL query
# param logic in app.py).
st.page_link("pages/2_Disclaimer.py", label="See the full Disclaimer →")

st.page_link("app.py", label="← Back to Vantage Screener")
