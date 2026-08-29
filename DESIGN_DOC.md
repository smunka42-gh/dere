# Vantage — design notes

A single-page stock screener over two equity markets — S&P 500 and Nifty
50. It surfaces companies that have pulled back relative to their own
recent trading history while still carrying analyst support, so a daily
glance is enough to decide whether anything is worth a closer look.

"Vantage" is a working name held in one constant (`theme.APP_NAME`) so
renaming is a one-line change.

---

## Architecture: batch scan, live re-filter

The site never fetches market data on page load.

- **`run_daily_scan.py`** fetches every ticker in every configured market
  once, computes the derived figures, and writes one JSON file per market
  (`output/latest_scan_<market>.json`) — see `markets.py` for what varies
  per market (currency, cap-tier thresholds, ticker source) and what
  doesn't (the scoring logic itself, which is market-agnostic).
- **`app.py`** only reads whichever market's file is currently selected.
  Every filter is pure arithmetic over numbers already loaded, so moving a
  slider re-scores the active market's tickers with no network calls and no
  perceptible lag.

Scanning ~500 S&P 500 tickers live on each page load would take minutes and
would hammer the data source. The split is what makes the filters feel
instant.

**Consequence worth knowing:** the site shows whatever scan was last
committed. It does not update itself. Refreshing the data means running the
scan and committing the new JSON.

### The one thing precomputed for the UI

The moving-average window is user-selectable (50 or 200 days), and changing
it needs a different average price — not something derivable from a saved
single number. So `evaluate_ticker()` precomputes upside for **every**
window into `sma_upside_by_window`, keyed by window as a string for clean
JSON round-tripping. Switching windows then stays pure arithmetic rather
than triggering a re-fetch of price history for 500 tickers.

---

## Composite Upside % — the metric everything is sorted by

A weighted blend of three upside measures, all using current price as the
denominator (the convention analyst upside is normally quoted in):

```
Composite Upside % = w₁ × (upside to moving average)
                   + w₂ × (upside to 52-week high)
                   + w₃ × (upside to analyst median target)
```

Default weights 50 / 25 / 25, adjustable in the UI and normalised, so the
sliders express *relative* importance — 50/50/50 means equal weight, the
same as 33/33/33.

**Why the moving average carries the dominant weight.** A 52-week high is
a single day and can be touched briefly without meaning much, whereas
trading below a moving average implies a pullback sustained across months
of real trading days — a stronger signal that a stock has genuinely, and
recently, pulled back.

**Why the analyst target is not weighted higher.** Analyst price targets
carry a well-documented optimism bias, so the target is deliberately not
allowed to dominate the two market-derived signals.

---

## The page

**Opportunity Map** — a treemap-style grid. Tile size follows market-cap
rank; colour follows Composite Upside %. Purely visual: no hover, click or
zoom, since the cards below are the way to drill in.

Built as a CSS grid of `<div>`s rather than a charting library. That was a
deliberate replacement: the library version couldn't do per-tile corner
radius or multi-element tile content, forced a root header strip, and
re-introduced float artefacts like `30.900000000000002%` in its own
formatting. Dropping it removed a dependency entirely.

Tile sizes come from a rank tier table rather than area proportional to
market cap — the index's cap distribution is top-heavy enough that a truly
proportional map lets a few tiles swallow the grid.

**Colour scale** runs amber → yellow-green → green, with red reserved for
genuinely negative values. Two deliberate choices:

- *Not red → green across the visible range.* Every tile on the map has
  already cleared the filters, so colouring the weakest one red would call
  a qualifying stock "bad". Red also already means "negative number"
  elsewhere in the UI, and one colour shouldn't carry two meanings.
- *Endpoints are the 5th/95th percentile, not raw min/max.* With raw
  endpoints a single outlier flattens everything else into one shade —
  observed with one ticker at +72% against a field clustered 10–30%.
  Clamping lets outliers saturate while the field spreads across the ramp.

**Today's Focus List** — a card per qualifying company: ticker, cap tier
and market cap, current price, Composite Upside % as a pill, a 52-week
range bar, and the three upside components.

The range bar is kept visually separate from the three upside figures on
purpose. Those measure room left to gain; "% above the low" measures
distance already travelled. Presenting them together would read as a fourth
upside to weigh alongside the others.

**Detail modal** — opened from a card's "+". Shows a full-width price scale
marking 52-week low, moving average, current price, analyst target and
52-week high, with links out to Yahoo and Google Finance. Deliberately
nothing else: the close, high, target and their upsides are all points *on*
the scale, so listing them underneath would repeat the same numbers.

A modal rather than an in-card expander because the scale needs more width
than a third of the page.

---

## Filters

All filters live in one `st.form`, so nothing recomputes until Apply is
pressed — the page never re-scores mid-drag.

Market cap range, its slider checkpoints, and the default itself are all
per-market (see `markets.py`) — the table below shows S&P 500's; switching
markets reseeds every filter-widget key to that market's own defaults so a
stale value from the previous market's scale can never persist.

| Filter | Default (S&P 500) |
|---|---|
| Market cap range | $100B – $10T |
| Max aggregate analyst rating | ≤ 2.0 |
| Moving-average window | 50 days |
| Min Composite Upside % | ≥ 10% |
| Composite Upside weights | 50 / 25 / 25 |

Analyst rating uses the source's 1–5 scale where **1 = Strong Buy** and
**5 = Strong Sell**, so a *lower* number is more bullish — easy to read
backwards, hence the in-UI tooltip.

The heatmap and the Focus List consume the same computed list, so they can
never show different sets under the same settings.

### Applied filters live in the URL

Applying writes the settings into the query string, so the back button, a
refresh and a bookmark all restore the same view. Only non-default values
appear, keeping the plain URL clean.

Session state alone can't do this: it is per-session, so any full page load
resets it. Values read back from the URL are validated against the same
ranges the sliders enforce — a query string is user-editable, so an invalid
value falls back to the default rather than reaching the filtering logic.
That includes guards for a reversed cap range and for all-zero weights.

---

## Ticker universe

Each market's constituent list is fetched from a public source (Wikipedia)
at scan time — see `markets.py` for the per-market fetcher. The
adjustments below are S&P 500-specific; Nifty 50 needs no equivalent (it
doesn't publish multiple ticker classes for the same company in its
index).

Fetched from the public S&P 500 constituent list. Two adjustments:

1. **Ticker format** — the source uses `BRK.B`; the data provider expects
   `BRK-B`.
2. **Dual-class deduplication** — the index lists 503 tickers for ~500
   companies. One ticker is kept per company:

   | Company | Kept | Dropped |
   |---|---|---|
   | Alphabet | GOOG | GOOGL |
   | Fox | FOXA | FOX |
   | News Corp | NWSA | NWS |

   The letter naming is **not** consistent across these. Alphabet's
   retail/non-voting line is the plain ticker; for Fox and News Corp
   voting control sits with the plain ticker and the "A" lines are the
   widely-traded ones. Each was checked individually rather than
   pattern-matched.

Displayed counts derive from the rows actually shown, not the scan's
`tickers_scanned` metadata — that records how many were *fetched* (503),
before deduplication.

**On the BSE Sensex.** Not offered as a third market, because it would add
no companies: its 30 constituents are a strict subset of Nifty 50's 50
(verified by diffing the two lists). Yahoo also returns only a single day
of price history for `.BO` tickers, so Sensex prices would have to come
from each company's NSE listing — the source Nifty 50 already uses.

---

## Working within Streamlit

The UI is Streamlit's own widgets restyled with injected CSS, not custom
components. Real interactivity comes free; styling is bounded by Streamlit's
actual DOM. A version bump can shift internal structure, so selectors are
worth re-checking after upgrades.

Constraints found the hard way, recorded so they aren't rediscovered:

- **`st.html()` sanitizes away `<style>`, `<link>` and `<svg>`.** The
  theme is injected with `st.markdown(textwrap.dedent(...),
  unsafe_allow_html=True)` instead. The dedent matters: in CommonMark a
  `<style>` tag at column 0 opens a raw-HTML block, but indented 4+ spaces
  it becomes a *code block* and renders as visible text. Webfonts load via
  `@import` inside the style block, since `<link>` is stripped too.
  *Diagnostic:* if styling appears to do nothing, check whether a CSS
  custom property resolves in the browser console before suspecting an
  individual selector.
- **No SVG anywhere.** The price scale and the brand mark are built from
  positioned `<div>`s for this reason.
- **Streamlit scopes font rules directly to its containers**, which
  outranks a broad `html, body` rule — headings, markdown and captions each
  need explicit overrides or they silently keep the default font.
- **Every widget needs an explicit static `key=`.** Without one, Streamlit
  derives widget identity partly from label text; a label containing a live
  value makes the widget "new" whenever that value changes, silently
  discarding uncommitted input.
- **`st.columns` children are flex items that shrink to their content**, so
  `width: 100%` on a descendant resolves against the shrunk box. Anything
  being aligned inside a column needs the element container stretched
  first.
- **An expander's body executes on every rerun**, collapsed or not — it is
  a visual toggle, not lazy loading. Anything expensive inside one runs for
  every row on every page load.
- **Imported modules are cached.** Editing the theme module needs a full
  server restart, not just a browser reload.

`.streamlit/config.toml` sets the light theme at source (Streamlit
auto-detects OS dark mode and themes its native widgets accordingly) and
hides the developer toolbar.

---

## Usage tracking

`analytics.py` counts page views, market switches, filter applies, and
which tickers get opened — a handful of counters in a module-level dict,
not a third-party analytics package. Both `streamlit-analytics` and its
maintained fork hard-require `google-cloud-firestore` even in in-memory
mode, which would pull in a real dependency chain for something this
small.

**Tradeoff, chosen deliberately: counts reset whenever the app process
restarts** (a code push, or ~12 idle hours on the free tier). Fine for a
rough sense of usage; not a durable history. View them by adding
`?analytics=on` to the site's URL — a convenience flag, not access
control, acceptable since it only ever exposes click counts, never
visitor data.

---

## Data source and limitations

Price history, analyst targets and recommendation counts come from Yahoo
Finance via the free `yfinance` library. This is an **unofficial,
unsupported** way of reading Yahoo's data — not guaranteed accurate,
complete, or continuously available. Acceptable for a personal tool; not
something to rely on without a fallback.

A known quirk of the source: some fields are occasionally stale or missing
for individual tickers. Code paths that consume them handle `None` rather
than assuming presence.

---

## Not financial advice

This tool encodes one person's personal rules in software. It is not
professional investment advice, is not from a licensed advisor, and should
be used at your own risk.

---

## Credits

- Market data via [Yahoo Finance](https://finance.yahoo.com) through the
  [`yfinance`](https://github.com/ranaroussi/yfinance) library
  (unofficial).
- S&P 500 and Nifty 50 constituent lists from Wikipedia's
  community-maintained tables.
- [Manrope](https://fonts.google.com/specimen/Manrope) typeface via Google
  Fonts (Open Font License).
- Heatmap concept — size by market cap, colour by signal — is the general
  finviz-style market map idea, built from scratch here rather than derived
  from any implementation.
- Visual language follows common "modern dashboard" conventions (rounded
  cards, restrained accent colour, generous whitespace); no assets or code
  taken from any product.
