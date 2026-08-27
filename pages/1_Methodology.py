"""
Vantage — Methodology page.

Plain-language explanation of the recommendation logic, for reference —
this mirrors DESIGN_DOC.md but written for reading on the site itself,
not as a build log.
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
st.page_link("app.py", label="← Back to Vantage")

st.title("Methodology")

st.markdown(f"""
{APP_NAME} is one page: a heatmap and a focus list, both driven by the
same metric — **Composite Upside %** — so there's one consistent story,
not several numbers that can disagree with each other.

### Composite Upside % — the one number that drives everything

A weighted blend of **three** upside measures, all using the same
"current price as denominator" convention (the standard way analyst
upside is quoted):

| Component | Weight | What it measures |
|---|---|---|
| Upside to 100-day moving average | **50%** | Has the stock genuinely, recently pulled back — not just noise |
| Upside to 52-week high | 25% | Distance from the single-day peak |
| Upside to analyst median target | 25% | Distance from where analysts expect it to go |

`Composite Upside % = 0.50×(upside to 100-day avg) + 0.25×(upside to 52w high) + 0.25×(upside to target)`

**Why the 100-day average, and why the dominant weight:** an earlier
version used the 52-week high alone as the "how cheap is this" signal —
but a peak can be touched for a single day and say very little about
where a stock actually, typically trades. A 100-day moving average
(the standard "intermediate trend" concept real traders already use)
requires a stock to show a genuine, sustained pullback across ~5 months
of real trading days, not a one-day spike or a few weeks of noise —
which fits the "accumulate in tranches, need real room" philosophy this
tool is built around. It replaced an even earlier attempt (bucketing a
full year of closes into a histogram and taking the most-visited price
band) that turned out to rely on as few as 10 days out of ~252 for some
stocks — not actually "a large number of days" despite the year-long
window, and prone to anchoring on a stale, months-old price regime.

**Why 25/25 instead of weighting the target higher:** analyst price
targets carry a well-documented, real optimism bias in practice — not
just caution for its own sake — so it's deliberately not weighted above
the peak, even though both are secondary to the dominant recent-average
signal.

**Qualification bar:** a stock must clear EVERY filter in the panel at
the top of the page — market cap range, aggregate rating, AND the
blended Composite Upside cutoff — to appear on the Focus List at all.
See "Live filters" below for the full list and today's defaults.

### Analyst quality bar

**Aggregate analyst rating ≤ 2.0 by default** on Yahoo's 1–5 scale,
where **1.0 = Strong Buy and 5.0 = Strong Sell** (easy to get backwards
— a *higher* number here is *worse*, worth stating plainly; see the
filter panel's own tooltip for what each of 1 through 5 means). A stock
that doesn't clear the current rating bar is excluded entirely from
the heatmap and the Focus List — not shown dimmed, just not there.

### Live filters (top-of-page panel)

Every control lives in one panel at the top of the page, laid out as a
**form** — dragging a slider or checking a box changes nothing by
itself; nothing recomputes until **Apply Filters** is clicked. That's
deliberate ("let user complete all options and then click
submit... dont execute with every change") — set everything the way
you want it, then commit it in one step, rather than the page
re-scoring 500+ stocks on every single drag.

- **Market cap range** — a $300M–$10T sliding scale (default
  **$100B–$10T**), not Large/Mid/Small buckets — market cap spans such
  an enormous range that a plain linear dollar slider would be useless
  at the small end, so the scale uses roughly log-spaced checkpoints
  instead. The Large/Mid/Small tag still shown on every Focus List card
  is separate, display-only classification, not tied to this filter.
- **Aggregate analyst rating** — the max allowed rating (default
  **≤2.0**).
- **Moving-average window** — 50 or 200 days (default 50). This is the
  one slicer that isn't purely "filter what's already saved":
  `evaluate_ticker()` precomputes upside-to-average for both windows
  during the nightly scan specifically so switching stays instant,
  rather than needing to re-fetch price history for 500+ stocks live.
- **Composite Upside cutoff** — the minimum blended % to qualify
  (default ≥10%).
- **Composite Upside weighting** — three sliders (shown side by side),
  one each for the moving-average / 52w-high / target components,
  normalized to always sum to 100% (default 50/25/25) — "50/50/50"
  means equal weight, same as "33/33/33". An earlier version also had
  three MORE sliders requiring each component to individually clear its
  own minimum upside, separate from this blended weighting — tried,
  then removed entirely as unnecessary complexity once in practice.

Whatever you apply is written into the page's web address, so the
browser's back button, a refresh, and a bookmark all bring back the
same view instead of resetting to the defaults. Only filters you've
actually changed appear there, so the address stays short — and you can
bookmark or share a particular screen and land straight back on it.

The heatmap and the Focus List always show the exact same set of
tickers under the currently APPLIED filters — one shared computation,
not two that could quietly drift apart. The panel also shows a live
count of how many tickers currently match, both right below the Apply
Filters button and again under the heatmap heading.

### What's on the page, and why

- **The heatmap** — box size = market cap, color = Composite Upside %,
  filtered by every applied filter in the panel above it. One lens,
  not several — an
  earlier version had 4 separate heatmap slices across 3 tabs (Delta 1,
  Delta 2, Composite Upside, and the max of the first two); simplified
  down to just Composite Upside since that's the number the whole page
  is organized around. Inspired by the general finviz-style market
  heatmap *concept* — built from scratch with Plotly, not copied from
  finviz's page or code. Color scale is a continuous auto-scaling
  gradient (not fixed bands) — it stretches to whatever today's actual
  min/max happen to be, which means the exact color-to-percentage
  mapping shifts slightly day to day.
- **The heatmap is purely visual** — no hover, click, or zoom; it's a
  glanceable map, not a navigation control. Use the Focus List below it
  to drill into any stock.
- **Today's Focus List** — a 3-across grid of cards, one per stock that
  clears the bar, sorted by Composite Upside %. Each card shows the
  ticker, company, cap tier + market cap, current price, the Composite
  Upside % as a pill, and the three upside components that feed it
  (moving average / 52-week high / analyst target).
- **The 52-week range bar** on each card marks where today's close sits
  between the 52-week low and high, with "% above low" alongside it.
  It's kept separate from the three upside figures on purpose: those
  measure room left to gain, while this measures distance already
  travelled — it is *not* a fourth upside to weigh against them.
- **"+" on any card** opens a window over the page showing the price
  scale at full width, with links out to Yahoo and Google Finance.
  Deliberately nothing else: the close, 52-week high, analyst target and
  their upsides are all points ON the scale, so listing them underneath
  would be the same numbers twice. It's a window rather than an in-card
  expander because the scale needs more width than a third of the page.
- **On the scale**, colour marks the three points worth finding fast —
  52-week low (red), current price (black, and the largest figure), and
  52-week high (green). The moving average and analyst target stay
  neutral so they don't compete; their upside percentages still carry
  the usual green/red.
- **The detail view** (opened from the heatmap or a Focus List card)
  is deliberately compact — current price, 52-week high,
  analyst target, Composite Upside % and its 3-part breakdown, analyst
  rating, and external links. An earlier version also showed live pre/
  post-market price separately from the saved close, the full analyst
  buy/hold/sell breakdown table, a 52-week range position bar, and the
  latest news headline — all still computed in `recommendation_logic.py`
  if a future "full research view" needs them, just trimmed from this
  page so it fits on one screen without scrolling.
- **External links** — every detail view links out to that ticker's
  Yahoo Finance and Google Finance pages (Google Finance's link is
  skipped for a ticker whose exchange isn't one {APP_NAME} knows how to map —
  currently NASDAQ and NYSE, which covers virtually all S&P 500 stocks).

### What's deliberately NOT included

- **Reddit / Twitter / Seeking Alpha sentiment** — considered and
  dropped for now. Twitter's API requires a paid tier to be usable at
  all; Reddit's is workable but rate-limited; Seeking Alpha has no real
  free API. Automated sentiment *scoring* on top of any of these would
  also be a substantial separate build. May revisit later.
- **Growth / Value / Blend classification** — no authoritative free-data
  source exists for this (it's a proprietary Morningstar "Style Box"
  concept). Only the raw ingredients to build a heuristic (P/E, PEG,
  growth rates) are available — skipped rather than presenting an
  unlabeled approximation as if it were an official classification.
- **Universe beyond the S&P 500** — starting scoped to ~500 well-known,
  liquid stocks. A larger universe (all US-tradeable equities) would
  need a paid data source for reliability at that scale.
- **Duplicate share classes** — the index actually lists 503 tickers for
  ~500 companies, because Alphabet, Fox and News Corp each have two
  classes listed separately. Only one per company is kept: **GOOG**,
  **FOXA** and **NWSA** — in each case the class ordinary investors
  actually trade. Note the naming isn't consistent: Alphabet's
  retail/non-voting class is the plain ticker (GOOG), while for Fox and
  News Corp it's the reverse — voting control sits with FOX/NWS, so the
  "A" tickers are the widely-traded ones.

### Data sources & limitations

Price history, analyst targets, recommendation counts, and live price
data all come from **Yahoo Finance**, via the free `yfinance` Python
library. This is an **unofficial, unsupported** way of reading Yahoo's
data — not guaranteed accurate, complete, or continuously available.
Acceptable for a personal tool; not something to bet anything critical
on without a fallback.

### Not financial advice

This tool encodes one person's personal rules and logic in software. It
is not professional investment advice, is not from a licensed advisor,
and should be used at your own risk.
""")

st.page_link("app.py", label="← Back to Vantage")
