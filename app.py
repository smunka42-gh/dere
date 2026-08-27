"""
Vantage — Daily Equity Recommendations, main website page.

This is the entry point Streamlit runs. It reads the most recent scan
results (produced by run_daily_scan.py) and displays them.

Note this file only DISPLAYS results — it doesn't run the scan itself.
That's deliberate: scanning 500 stocks live on every page load would be
far too slow for a webpage. See DESIGN_DOC.md for the full reasoning.

The "Methodology" page lives in pages/1_Methodology.py — Streamlit
automatically turns any file in a pages/ folder into a separate page,
linked from the sidebar.

Layout (2026-08-27, second redesign — simplified back to one page):
disclaimer, a top-of-page filter form, ONE heatmap (colored by
Composite Upside %, the same metric that drives the focus list below
it — earlier had 4 separate heatmap slices across 3 tabs, but the
actual workflow is "look at the heatmap, then check today's picks,"
not browsing multiple exploratory lenses), then "Today's Focus List" —
the tickers that actually clear the bar. Clicking any ticker (a heatmap
box or a Focus List row) shows the SAME compact detail card —
essentials only (price, 52-week high, target, Composite Upside
breakdown, rating, external links), not the full multi-section
breakdown the very first version had (live pre/post-market metrics,
full analyst buy/hold/sell table, latest news) — deliberate: this
page is a daily glance, not a research report, so the detail view
should fit on one screen without scrolling. The ad-hoc ticker search
that used to sit here was removed entirely (2026-08-27: "dont
need that at all anymore") — everything now works off the saved scan.
"""

import json
from pathlib import Path
from datetime import datetime, timezone

import streamlit as st

from sp500_tickers import DUPLICATE_SHARE_CLASSES_TO_DROP
from recommendation_logic import (
    COMPOSITE_UPSIDE_THRESHOLD_PCT,
    SMA_WINDOW_DAYS,
    SMA_WINDOW_OPTIONS,
    COMPOSITE_WEIGHT_RECENT_AVG,
    COMPOSITE_WEIGHT_PEAK,
    COMPOSITE_WEIGHT_TARGET,
)
from theme import APP_NAME, inject_theme_css, POSITIVE_COLOR, NEGATIVE_COLOR, CAP_TIER_COLORS

OUTPUT_FILE = Path(__file__).parent / "output" / "latest_scan.json"
MAX_BANNER_NAME_LENGTH = 40


# layout="wide" gives the heatmap and focus-list cards real horizontal
# room — part of the "Minimal Data-First" visual direction review
# picked (2026-08-27).
st.set_page_config(page_title=f"{APP_NAME} — Daily Equity Recommendations", page_icon="📈", layout="wide")
# Must run immediately after set_page_config, before any other widget —
# see theme.py for why.
inject_theme_css()


def load_scan_results() -> dict | None:
    """Read the most recent scan results from disk. Returns None if no scan has run yet."""
    if not OUTPUT_FILE.exists():
        return None
    with open(OUTPUT_FILE) as f:
        scan = json.load(f)

    # `sp500_tickers.py` already excludes these from future scans, but a
    # scan file saved before that change was added would still have them —
    # filtered here too so today's page reflects it without waiting on
    # tomorrow's nightly scan to overwrite the file.
    for key in ("all_results", "recommendations"):
        scan[key] = [r for r in scan[key] if r["ticker"] not in DUPLICATE_SHARE_CLASSES_TO_DROP]

    return scan


def truncate_company_name(name: str, max_length: int = MAX_BANNER_NAME_LENGTH) -> str:
    if len(name) <= max_length:
        return name
    return name[:max_length].rstrip(", ") + "…"


def format_market_cap(market_cap: float | None) -> str:
    """
    Human-readable market cap for the Focus List header (2026-08-27,
    wants the actual number alongside the Large/Mid/Small tag,
    not just the tier name). Same T/B/M unit breakpoints as
    MARKET_CAP_OPTIONS above, but computed for the exact real value
    rather than snapped to one of that list's fixed checkpoints.
    """
    if market_cap is None:
        return "cap n/a"
    if market_cap >= 1_000_000_000_000:
        return f"${market_cap / 1_000_000_000_000:.2f}T"
    if market_cap >= 1_000_000_000:
        return f"${market_cap / 1_000_000_000:.1f}B"
    return f"${market_cap / 1_000_000:.0f}M"


def clean_company_name(name: str | None) -> str:
    """
    Yahoo returns some names with a trailing article in brackets —
    "Home Depot, Inc. (The)", "Kroger Co. (The)". review asked what the
    "(The)" was doing there (2026-08-27); it's a data convention, not
    part of the brand. Moved to the front where it belongs rather than
    dropped, so the name still reads correctly.
    """
    if not name:
        return ""
    if name.endswith(" (The)"):
        return "The " + name[: -len(" (The)")]
    return name


def build_external_links_html(r: dict, size_class: str = "") -> str:
    """
    Yahoo / Google Finance links as compact brand-marked chips.

    Shared by the Focus List card and the detail modal (2026-08-27,
    "why dont we just bring the y and g links to the main card so
    we can click on them directly... without needing to click the + sign")
    — one builder rather than two copies, so they can't drift apart.

    Plain <a> rather than st.link_button so they can sit inline inside
    st.html markup. These leave the app entirely, so unlike the
    Methodology link there's no session state worth preserving.

    Brand LETTERS, not logos: st.html() strips <svg>, and an external
    <img> would put a network dependency into a local tool.

    Google Finance is skipped for a ticker whose exchange isn't one we
    know how to map (currently NASDAQ/NYSE, which covers effectively all
    of the S&P 500).
    """
    yahoo_url = f"https://finance.yahoo.com/quote/{r['ticker']}"
    cls = f"vg-ext {size_class}".strip()
    html = (
        f'<a class="{cls} vg-ext-y" href="{yahoo_url}" target="_blank" '
        f'rel="noopener" title="Open {r["ticker"]} in Yahoo Finance">Y!</a>'
    )
    google_exchange = r.get("google_finance_exchange")
    if google_exchange:
        google_url = f"https://www.google.com/finance/quote/{r['ticker']}:{google_exchange}"
        html += (
            f'<a class="{cls} vg-ext-g" href="{google_url}" target="_blank" '
            f'rel="noopener" title="Open {r["ticker"]} in Google Finance">G</a>'
        )
    return html


def build_price_scale_html(r: dict, sma_window: int) -> str:
    """
    The price scale shown in the "+" detail modal — a real horizontal
    number line with five reference points.

    Built from absolutely-positioned <div>s, NOT SVG: st.html() silently
    strips <svg> entirely (confirmed against the live DOM — 0 <svg>
    elements despite generating them).

    2026-08-27 rework, all from the feedback on the modal:
    - Value and % are STACKED on separate lines rather than sharing one.
      That roughly halves each label's width, which is what makes two
      nearby points stop crowding each other ("if lets say 50d avg and
      current price are close to each other, there is still a way to not
      let it clutter").
    - "Now" is the point to find first, but it is NOT made bigger —
      every value is the same 11.5px. It's separated by contrast alone:
      the only near-black value, weight 800, and a 13px marker vs 9px.
    - Colour is spent on exactly three points — 52W Low (red), Now
      (near-black), 52W High (green). The moving average and analyst
      target are deliberately muted gray: their % figures already carry
      green/red, and colouring all five would
      make the scale busier, not clearer. That directly serves the
      "still cluttery" complaint rather than fighting it.

    Deliberately NOT clamped to the 52-week high — the analyst target
    can legitimately sit ABOVE it (a bullish analyst sees room past the
    past year's peak), and clamping would hide exactly the signal
    Composite Upside % exists to catch.

    The moving average's DOLLAR price isn't stored anywhere — only its
    upside % is (sma_upside_by_window, precomputed per window during the
    scan). Reconstructed here algebraically from that percentage and the
    current price, the exact inverse of compute_upside_pct()'s formula
    (upside = (ref − current) / current × 100 ⟹ ref = current × (1 +
    upside / 100)) — exact, not an approximation, and needs no rescan.
    """
    current = r.get("most_recent_close")
    low = r.get("fifty_two_week_low")
    high = r.get("fifty_two_week_high")
    target = r.get("analyst_target_median")
    sma_upside = r.get("upside_to_recent_avg_pct")
    high_upside = r.get("upside_to_52w_high_pct")
    target_upside = r.get("upside_to_target_pct")
    sma_price = current * (1 + sma_upside / 100) if None not in (current, sma_upside) else None
    up_from_low = (current - low) / low * 100 if None not in (current, low) and low else None

    def _price(v: float) -> str:
        """
        Cents dropped on the scale (2026-08-27: "should we remove
        decimal points?"). Shorter labels are the cheapest way to buy
        horizontal room, and the exact price with cents is already on the
        card. Precision scales with magnitude rather than being dropped
        flat — at $8 the cents ARE the signal, at $733 they're noise.
        """
        if v >= 100:
            return f"${v:,.0f}"
        if v >= 10:
            return f"${v:,.1f}"
        return f"${v:,.2f}"

    neutral = "var(--vg-text-muted)"
    # (label, value, pct, pct suffix, accent colour, value colour, is_hero)
    #
    # 2026-08-27, third pass on the scale:
    # - "Current Price" back to "NOW". The long label was widening the
    #   left cluster on tickers where price sits near the 52-week low;
    #   the hero styling (largest, boldest) is what makes it findable,
    #   not the label text, so the short form costs nothing.
    # - The $ VALUE is now coloured too, not just the label word — with
    #   every value in the same near-black, the hero's larger size was
    #   the only differentiator and it wasn't possible to tell it was bigger.
    # - The "vs low" suffix dropped and the % takes the normal green/red
    #   treatment, by design.
    #
    # ALL FIVE VALUES ARE THE SAME SIZE (2026-08-27, final call:
    # "you can highlight it in other ways (color coding) vs making it
    # bigger"). Every point is 11.5px; "Now" is separated purely by
    # CONTRAST instead:
    #   - it is the only near-black value, because the moving average and
    #     analyst target were demoted to muted gray here — that's what
    #     makes black distinctive rather than shared with two others
    #   - weight 800 against their 700
    #   - a 13px marker against 9px
    # 52W Low and 52W High keep red/green, so the scale reads as three
    # coloured anchors (low / now / high) with two quiet reference points
    # between them.
    points = [
        ("52W Low", low, None, "", "var(--vg-negative)", "var(--vg-negative)", False),
        (f"{sma_window}D Avg", sma_price, sma_upside, "", neutral, neutral, False),
        ("Now", current, up_from_low, "", "var(--vg-text)", "var(--vg-text)", True),
        ("Analyst Target", target, target_upside, "", neutral, neutral, False),
        ("52W High", high, high_upside, "", "var(--vg-positive)", "var(--vg-positive)", False),
    ]
    valid = [p for p in points if p[1] is not None]
    if len(valid) < 2:
        return '<div style="font-size:12px; color:var(--vg-text-muted);">Not enough price data for the scale.</div>'

    values = [p[1] for p in valid]
    lo, hi = min(values), max(values)
    span = hi - lo if hi > lo else 1

    # Sorted left-to-right by POSITION, not by identity, so the
    # above/below alternation always separates the two closest points
    # regardless of which two they happen to be.
    ordered = sorted(valid, key=lambda p: p[1])
    marker_pos = [(p[1] - lo) / span * 100 for p in ordered]

    # Labels alternate above/below the track, so immediate neighbours
    # can never collide. The remaining risk is points TWO apart landing
    # on the same side within a label's width of each other — the "2 or
    # 3 signals close together" case. Handled by nudging same-side
    # labels apart to a minimum gap, left-to-right then right-to-left so
    # the correction can't push the last one off the edge. The MARKER
    # stays on its true value; only the label text slides, and a
    # connector line is drawn whenever the two separate enough to
    # notice, so a nudged label can't silently misreport its position.
    MIN_GAP = 9.5
    label_pos = list(marker_pos)
    for side in (0, 1):
        idxs = [i for i in range(len(ordered)) if i % 2 == side]
        for k in range(1, len(idxs)):
            prev_i, cur_i = idxs[k - 1], idxs[k]
            if label_pos[cur_i] - label_pos[prev_i] < MIN_GAP:
                label_pos[cur_i] = label_pos[prev_i] + MIN_GAP
        for k in range(len(idxs) - 2, -1, -1):
            cur_i, next_i = idxs[k], idxs[k + 1]
            if label_pos[next_i] > 100:
                label_pos[next_i] = 100
            if label_pos[next_i] - label_pos[cur_i] < MIN_GAP:
                label_pos[cur_i] = label_pos[next_i] - MIN_GAP
    label_pos = [min(max(p, 0), 100) for p in label_pos]

    parts = []
    for i, (label, value, pct, suffix, colour, value_colour, is_hero) in enumerate(ordered):
        mpos = min(max(marker_pos[i], 0.6), 99.4)
        lpos = label_pos[i]
        dot = 13 if is_hero else 9
        parts.append(
            f'<div style="position:absolute; left:{mpos:.2f}%; top:50%; '
            f"transform:translate(-50%,-50%); width:{dot}px; height:{dot}px; "
            f"border-radius:50%; background:{colour}; border:2px solid var(--vg-bg); "
            f'box-shadow:0 0 0 1px var(--vg-border); z-index:3;"></div>'
        )

        # Connector, only when the label had to move far enough that the
        # eye would otherwise mis-pair it with the wrong marker.
        if abs(lpos - mpos) > 1.5:
            left, right = sorted((mpos, lpos))
            vert = "bottom:calc(50% + 6px); height:14px;" if i % 2 == 0 else "top:calc(50% + 6px); height:14px;"
            parts.append(
                f'<div style="position:absolute; left:{left:.2f}%; width:{right - left:.2f}%; '
                f'{vert} border-top:1px solid var(--vg-border); z-index:1;"></div>'
            )

        # Labels near an edge anchor to it rather than centring, so a
        # wide value can only ever grow inward.
        if lpos <= 10:
            anchor = "left:0; transform:none; text-align:left;"
        elif lpos >= 90:
            anchor = "right:0; left:auto; transform:none; text-align:right;"
        else:
            anchor = f"left:{lpos:.2f}%; transform:translateX(-50%); text-align:center;"
        offset = "bottom:56px;" if i % 2 == 0 else "top:56px;"

        pct_html = ""
        if pct is not None:
            pct_colour = "var(--vg-positive)" if pct >= 0 else "var(--vg-negative)"
            shown = f"{pct:+.0f}%" if abs(pct) >= 100 else f"{pct:+.1f}%"
            pct_html = (
                f'<div style="color:{pct_colour}; font-weight:700; font-size:10px; '
                f'font-variant-numeric:tabular-nums; line-height:1.3;">{shown}{suffix}</div>'
            )
        parts.append(
            f'<div style="position:absolute; {anchor} {offset} white-space:nowrap; z-index:2;">'
            f'<div style="color:{colour}; font-size:8.5px; font-weight:700; '
            f'text-transform:uppercase; letter-spacing:0.05em; line-height:1.35;">{label}</div>'
            # One size for every value. Size went 16 → 19 → 16 → 13 across
            # three rounds before review settled it: differentiate "Now"
            # by contrast, not scale. See the points table above for what
            # carries the emphasis instead.
            f'<div style="color:{value_colour}; font-weight:{800 if is_hero else 700}; '
            f'font-size:11.5px; font-variant-numeric:tabular-nums; '
            f'line-height:1.25;">{_price(value)}</div>'
            f"{pct_html}</div>"
        )

    return (
        f'<div style="position:relative; height:100px; margin:0 4px;">'
        f'<div style="position:absolute; left:0; right:0; top:calc(50% - 1.5px); height:3px; '
        f'background:var(--vg-border); border-radius:2px;"></div>'
        f'{"".join(parts)}'
        f"</div>"
    )


@st.dialog("Detail", width="large")
def show_detail_dialog(r: dict, sma_window: int, weights: tuple[float, float, float]) -> None:
    """
    The full card, opened from a tile's "+" button (2026-08-27:
    "when we click the + button, we can open up the full card (straight
    from the tile) that also shows the scale").

    A modal, rather than an expander inside the tile, specifically
    BECAUSE of the price scale: a tile is one third of the page wide,
    and the scale needs real width to be readable — that width problem
    is what drove the earlier switch from cards to full-width rows in
    the first place. st.dialog(width="large") gives the scale a wide
    canvas without giving up the 3-across grid, which is what lets both
    work together instead of trading off against each other.

    Stripped to one header line plus the scale (2026-08-27: "we
    should just have HD $334.1B | yahoo finance link | google finance
    link and then the scale below and thats it"). Everything else that
    used to be here was cut BECAUSE THE SCALE ALREADY SHOWS IT — the
    close, 52-week high, analyst target and their upsides are all points
    ON the scale, so the metric row underneath was the same four numbers
    a second time. Also gone: the "Strong Buy pick" badge (a whole line
    to say something the filters already guarantee — every card in the
    list cleared them), the repeated "HD — Home Depot, Inc." heading,
    and the sector line.

    `weights` is still accepted so callers don't have to change, but is
    no longer needed for display now that the formula caption is gone.

    NOTE: analyst rating is now shown nowhere in the UI. It's still a
    live filter, and still on the Methodology page — flagged to review
    rather than quietly re-added.
    """
    cap_tier = r.get("market_cap_tier")
    tier_color = CAP_TIER_COLORS.get(cap_tier, "#c3cad1")
    company = truncate_company_name(clean_company_name(r.get("company_name")), max_length=52)

    links = build_external_links_html(r)

    st.html(
        f'<div class="vg-modal-head">'
        f'<span class="vg-modal-ticker">{r["ticker"]}</span>'
        f'<span class="vg-cap-tag" style="background:{tier_color};">'
        f'{format_market_cap(r.get("market_cap"))}</span>'
        f'<span class="vg-modal-co">{company}</span>'
        f'<span class="vg-modal-links">{links}</span>'
        f"</div>"
    )
    st.html(build_price_scale_html(r, sma_window))


def render_focus_card(r: dict, sma_window: int, weights: tuple[float, float, float]) -> None:
    """
    One tile in the 3-across "Today's Focus List" grid (2026-08-27 —
    back to the card grid from the Option 3 mockup, after a spell as
    full-width rows).

    What the tile carries: ticker, market cap + tier tag,
    company name, and the three upside components that feed Composite
    Upside % (to the moving average, to the 52-week high, to the analyst
    target). The blended Composite Upside % sits top-right as a pill —
    it's the list's sort key and the one number the whole page is
    organised around, so it's what gives the grid its visual hierarchy.

    The price scale is deliberately NOT on the tile — it needs more
    width than a third of the page. It lives in the "+" modal instead
    (see show_detail_dialog).
    """
    full_company_name = r.get("company_name") or r["ticker"]
    cap_tier = r.get("market_cap_tier")
    tier_color = CAP_TIER_COLORS.get(cap_tier, "#c3cad1")
    composite = r.get("composite_upside_pct")

    def _stat(label: str, pct: float | None) -> str:
        if pct is None:
            value_html = '<div class="vg-stat-val">n/a</div>'
        else:
            tone = "vg-pos" if pct >= 0 else "vg-neg"
            value_html = f'<div class="vg-stat-val {tone}">{pct:+.1f}%</div>'
        return f'<div><div class="vg-stat-label">{label}</div>{value_html}</div>'

    # 52-week range bar — where today's price sits between the 52w low
    # and high, plus how far it has run from the low (2026-08-27,
    # "how far up the current price is wrt 52w low... thats the
    # only signal missing in the cards").
    #
    # Deliberately NOT a fourth column in the stats row below. Those
    # three are all FORWARD-looking upside — room left to gain. "% above
    # the low" is BACKWARD-looking — distance already travelled. Sitting
    # them in one row would read as a fourth upside to weigh alongside
    # the others, the same confusion the price scale avoids by giving
    # 52W Low no upside figure of its own.
    #
    # A range bar rather than a bare number because the position answers
    # both halves at once: how far it has run, and how much room is left
    # to the high. `position_in_range_pct` exists in the scan data but is
    # recomputed here from low/high/close so it always agrees with the
    # dollar figures shown on the same card.
    low = r.get("fifty_two_week_low")
    high = r.get("fifty_two_week_high")
    current = r.get("most_recent_close")
    range_html = ""
    if None not in (low, high, current) and high > low:
        position = min(max((current - low) / (high - low) * 100, 0), 100)
        above_low = (current - low) / low * 100 if low else None
        # Drop the decimal past 100%: a stock that has run from $48 to
        # $1,499 shows "+2995% above low", and at "+2995.3%" the value
        # crowds the "52W range" label on the same line. The tenth of a
        # percent is noise at that magnitude anyway.
        above_low_html = (
            f'<span class="vg-range-val">'
            f'{above_low:+.0f}% above low</span>'
            if above_low is not None and abs(above_low) >= 100
            else f'<span class="vg-range-val">{above_low:+.1f}% above low</span>'
            if above_low is not None
            else ""
        )
        range_html = (
            f'<div class="vg-range">'
            f'<div class="vg-range-track">'
            f'<div class="vg-range-fill" style="width:{position:.1f}%;"></div>'
            f'<div class="vg-range-dot" style="left:{position:.1f}%;"></div>'
            f"</div>"
            f'<div class="vg-range-cap"><span>52W range</span>{above_low_html}</div>'
            f"</div>"
        )

    pill_tone = "vg-pill-pos" if composite is not None and composite >= 0 else "vg-pill-neg"
    pill = (
        f'<div class="vg-pill {pill_tone}">{composite:+.1f}%</div>'
        if composite is not None
        else '<div class="vg-pill">n/a</div>'
    )

    with st.container(border=True, key=f"focuscard-{r['ticker']}"):
        st.html(
            f'<div class="vg-card-head">'
            f"<div>"
            f'<div class="vg-card-ticker">{r["ticker"]}</div>'
            f'<div class="vg-card-company">'
            f"{truncate_company_name(clean_company_name(full_company_name), max_length=32)}</div>"
            f"</div>{pill}</div>"
            f'<div class="vg-card-tagrow">'
            f'<span class="vg-cap-tag" style="background:{tier_color};">'
            f'{cap_tier or "Cap n/a"} · {format_market_cap(r.get("market_cap"))}</span>'
            f'<span class="vg-card-links">{build_external_links_html(r, "vg-ext-sm")}</span></div>'
            f'<div class="vg-card-price">${r["most_recent_close"]:,.2f}</div>'
            f"{range_html}"
            f'<div class="vg-card-stats">'
            f'{_stat(f"{sma_window}D Avg", r.get("upside_to_recent_avg_pct"))}'
            f'{_stat("52W High", r.get("upside_to_52w_high_pct"))}'
            f'{_stat("Target", r.get("upside_to_target_pct"))}'
            f"</div>"
        )
        # Rendered LAST in the card's flow but positioned into the top-
        # right corner by CSS (2026-08-27: a "+" beside the %
        # pill "is more intuitive" than a button at the bottom).
        # Streamlit buttons are block elements and can't be nested into
        # the st.html header markup above, so the card is a positioning
        # context and the button is absolutely placed into it — it stays
        # a real st.button, with click handling intact, and only its
        # position changes. No label text and no `help` tooltip — review
        # wants "just a + sign"; a "+" in a card's corner is a
        # well-understood affordance on its own.
        if st.button("+", key=f"detailbtn-{r['ticker']}"):
            show_detail_dialog(r, sma_window, weights)


def _signal_color(pct: float, lo: float, hi: float) -> str:
    """
    Map a Composite Upside % to a tile color on a red→neutral→green
    scale, auto-scaled to the CURRENT visible set (same convention the
    old Plotly gradient used: the extremes stretch to whatever today's
    min/max happen to be, so the exact color→% mapping shifts slightly
    day to day).

    Interpolates in plain RGB between three anchors taken from the
    Option 3 mockup's own tiles, so the map and the rest of the theme
    stay the same family of colors.
    """
    # Positive ramp is AMBER → yellow-green → GREEN, deliberately not
    # red → green (2026-08-27, review proposed red for the weakest
    # qualifier). Reasoning worth keeping: the composite cutoff slider
    # bottoms out at 0, so every tile on this map has already CLEARED
    # every filter — colouring the weakest one red would say "bad"
    # about a stock with double-digit upside that passed every bar.
    # Red also already means something specific in this app (a
    # genuinely negative number, e.g. an ORCL trading above its 50-day
    # average), and one colour can't carry two meanings. Amber gives
    # the same full visual range while reading as "modest", not "loss".
    weak_pos = (214, 152, 62)    # #d6983e amber
    mid_pos = (150, 184, 92)     # #96b85c yellow-green
    dark_pos = (31, 125, 76)     # #1f7d4c — theme positive
    light_neg = (231, 150, 144)  # #e79690
    dark_neg = (193, 62, 52)     # #c13e34

    if pct >= 0:
        # Normalised across the POSITIVE tiles actually on screen, not
        # across 0..hi. In practice the filters mean every tile is
        # already above the Composite Upside cutoff (often all >+10%),
        # so anchoring at 0 squeezed the whole set into a narrow band of
        # near-identical greens — the map stopped distinguishing
        # anything. Stretching across the visible range is also what the
        # Plotly gradient this replaced did, so the "exact colour-to-%
        # mapping shifts day to day" caveat in the Methodology page
        # still holds.
        floor = max(lo, 0.0)
        span = hi - floor
        t = (pct - floor) / span if span > 0 else 0.5
        # Two-segment ramp through the mid stop, so the middle of the
        # range lands on yellow-green rather than the muddy olive a
        # straight amber→green RGB interpolation would pass through.
        t = min(max(t, 0.0), 1.0)
        if t < 0.5:
            start, end, t = weak_pos, mid_pos, t * 2
        else:
            start, end, t = mid_pos, dark_pos, (t - 0.5) * 2
    else:
        ceiling = min(hi, 0.0)
        span = ceiling - lo
        t = (ceiling - pct) / span if span > 0 else 0.5
        start, end = light_neg, dark_neg

    t = min(max(t, 0.0), 1.0)
    r, g, b = (round(start[i] + (end[i] - start[i]) * t) for i in range(3))
    return f"#{r:02x}{g:02x}{b:02x}"


# Tile sizes for the heatmap grid, as (columns, rows) spans on a
# 12-column grid — biggest company first. Taken from the Option 3
# mockup's own hand-tuned packing rather than computed from raw market
# cap: a strictly proportional area would make the largest few tiles
# swallow the grid (the S&P 500's cap distribution is extremely
# top-heavy), which is exactly what the mockup's tiering avoids while
# still reading as "bigger company, bigger tile".
HEATMAP_TILE_TIERS = [
    (3, (4, 6)),    # top 3
    (4, (3, 4)),    # next 4
    (8, (2, 3)),    # next 8
    (None, (2, 2)),  # everything else
]


def render_heatmap(filtered_results: list[dict], color_field: str, label_field: str, chart_key: str) -> None:
    """
    Box size = market cap rank, color = Composite Upside %.

    Rebuilt 2026-08-27 as a plain CSS grid, replacing a Plotly treemap.
    comparing the built page against the Option 3 mockup and
    asked for the mockup's heatmap specifically: rounded 6px tiles with
    3px gaps, ticker in white, company name beneath it, and the % large
    at the tile's bottom-left. Plotly's treemap couldn't give any of
    that — no per-tile corner radius, no multi-element tile layout, and
    it forced an "All S&P 500" root strip across the top.

    Dropping Plotly also removed the whole class of problems that came
    with it: the staticPlot config needed to kill its click/zoom
    behaviour, its own number formatting re-introducing floats like
    "30.900000000000002%", and the sector-grouping path bug. A grid of
    <div>s has none of that and matches the mockup exactly.

    Takes an ALREADY-FILTERED list — the heatmap and the Focus List
    consume the same qualifying_results so they can never disagree.

    Inspired by the general finviz-style heatmap *concept* (size by
    market cap, color by signal), built from scratch.
    """
    chart_data = [
        r for r in filtered_results
        if r.get("market_cap") and r.get(color_field) is not None
    ]
    if not chart_data:
        st.caption("Not enough data to draw this heatmap.")
        return None

    chart_data = sorted(chart_data, key=lambda r: r["market_cap"], reverse=True)
    signals = [r[color_field] for r in chart_data]

    # Colour-ramp endpoints come from the 5th/95th percentile, NOT the
    # raw min/max (2026-08-27). With raw endpoints a single outlier
    # ruins the map: one stock at +72% against a field clustered
    # 10–30% stretched the scale so far that 28 of 29 tiles landed in
    # the bottom third of the ramp and came out near-identical amber —
    # the exact loss of differentiation this colouring exists to
    # prevent. Clamping means outliers simply saturate at full green
    # and the rest of the field spreads across the whole ramp.
    # The legend still reports the true min/max separately.
    ordered_signals = sorted(signals)
    def _percentile(p: float) -> float:
        if len(ordered_signals) == 1:
            return ordered_signals[0]
        idx = min(int(p * (len(ordered_signals) - 1)), len(ordered_signals) - 1)
        return ordered_signals[idx]

    lo, hi = _percentile(0.05), _percentile(0.95)
    if hi <= lo:  # every tile identical, or too few to spread
        lo, hi = min(signals), max(signals)
    true_lo, true_hi = min(signals), max(signals)

    tiles = []
    for i, r in enumerate(chart_data):
        # Walk the tier table to find this rank's tile span.
        rank_remaining, (col_span, row_span) = i, HEATMAP_TILE_TIERS[-1][1]
        for count, span in HEATMAP_TILE_TIERS:
            if count is None or rank_remaining < count:
                col_span, row_span = span
                break
            rank_remaining -= count

        pct = r[color_field]
        color = _signal_color(pct, lo, hi)
        # Pick the text colour from the tile's own brightness rather
        # than always using white: the amber end of the ramp is far
        # lighter than the deep-green end, and white-on-amber is close
        # to unreadable. Standard perceived-luminance weights (human
        # eyes are most sensitive to green, least to blue).
        red, green, blue = (int(color[i:i + 2], 16) for i in (1, 3, 5))
        luminance = (0.299 * red + 0.587 * green + 0.114 * blue) / 255
        text_color = "#16181d" if luminance > 0.62 else "#ffffff"
        big = col_span >= 3
        company = truncate_company_name(clean_company_name(r.get("company_name")), max_length=22)
        company_html = (
            f'<div class="vg-tile-co">{company}</div>' if big and company else ""
        )
        tiles.append(
            f'<div class="vg-tile" style="grid-column:span {col_span}; '
            f'grid-row:span {row_span}; background:{color}; color:{text_color};">'
            f'<div class="vg-tile-tkr" style="font-size:{16 if big else 12.5}px;">{r["ticker"]}</div>'
            f"{company_html}"
            f'<div class="vg-tile-pct" style="font-size:{17 if big else 11.5}px;">{pct:+.1f}%</div>'
            f"</div>"
        )

    # Legend gradient is built from the SAME _signal_color() the tiles
    # use, sampled across the visible range — so it can't drift out of
    # sync with them the way a separately hardcoded CSS gradient would.
    # Endpoints are the real min/max on screen, not a fixed ±scale.
    stops = ", ".join(
        _signal_color(lo + (hi - lo) * i / 8, lo, hi) for i in range(9)
    )
    legend = (
        f'<div class="vg-legend"><span class="vg-legend-label">Signal</span>'
        f'<span class="vg-legend-bar" style="background:linear-gradient(90deg,{stops});"></span>'
        f'<span class="vg-legend-nums">{true_lo:+.1f}%&nbsp;&nbsp;&nbsp;&nbsp;{true_hi:+.1f}%</span></div>'
    )
    st.html(f'<div class="vg-heatmap">{"".join(tiles)}</div>{legend}')
    return None


def compute_live_evaluation(
    r: dict,
    sma_window: int,
    weights: tuple[float, float, float],
    rating_threshold: float,
    composite_cutoff: float,
    cap_range: tuple[float, float],
) -> dict:
    """
    Returns a NEW dict — a shallow copy of `r` with composite_upside_pct,
    upside_to_recent_avg_pct, recommended, and skip_reason all
    RECOMPUTED against the current sidebar slicer settings, instead of
    the fixed values (100-day avg, 50/25/25 weights, rating ≤1.5,
    upside ≥10%) saved at scan time (2026-08-27). A stock qualifies when its aggregate rating is
    AT OR BELOW `rating_threshold` (briefly tried as 5 rating-bucket
    checkboxes, reverted back to a single slider — reverted after
    seeing the checkbox dropdown in practice).

    Pure arithmetic over numbers already loaded from the saved scan —
    no live API calls — so this is cheap enough to re-run for all 500+
    tickers on every single slider move without any lag.

    "recommended" and "skip_reason" get recomputed too (not just the
    number) so the badge and the "not a current recommendation" message
    in render_detail_card stay honest about THIS turn's slicer
    settings, rather than showing a stale reason computed under the old
    fixed defaults.

    Individual-component minimum-upside filters (SMA/52w-high/target)
    were tried alongside the blended Composite Upside cutoff and then
    removed entirely (2026-08-27: "remove the min upside
    individual components 3 sliders completely") — the blended cutoff
    below is the only upside qualification bar now.
    """
    sma_upside = r.get("sma_upside_by_window", {}).get(str(sma_window))
    peak_upside = r.get("upside_to_52w_high_pct")
    target_upside = r.get("upside_to_target_pct")
    rating = r.get("recommendation_mean")
    market_cap = r.get("market_cap")
    cap_min, cap_max = cap_range

    composite = None
    if sma_upside is not None and peak_upside is not None and target_upside is not None:
        w_avg, w_peak, w_target = weights
        composite = round(w_avg * sma_upside + w_peak * peak_upside + w_target * target_upside, 2)

    recommended = True
    skip_reason = None
    if composite is None:
        recommended = False
        skip_reason = "Missing analyst target price or price history for this moving-average window"
    elif rating is None:
        recommended = False
        skip_reason = "No analyst rating available"
    elif rating > rating_threshold:
        recommended = False
        skip_reason = f"Analyst rating ({rating:.2f}) above your rating filter (≤{rating_threshold:.1f})"
    elif market_cap is None or market_cap < cap_min or market_cap > cap_max:
        recommended = False
        skip_reason = "Market cap outside your selected range" if market_cap is not None else "Market cap unavailable"
    elif composite < composite_cutoff:
        recommended = False
        skip_reason = f"Composite Upside ({composite:+.1f}%) below your cutoff (≥{composite_cutoff:.0f}%)"

    updated = dict(r)
    updated["composite_upside_pct"] = composite
    updated["upside_to_recent_avg_pct"] = sma_upside
    updated["recommended"] = recommended
    updated["skip_reason"] = skip_reason
    return updated


MARKET_CAP_OPTIONS = [
    ("$300M", 300_000_000), ("$500M", 500_000_000),
    ("$1B", 1_000_000_000), ("$2B", 2_000_000_000), ("$5B", 5_000_000_000),
    ("$10B", 10_000_000_000), ("$20B", 20_000_000_000), ("$50B", 50_000_000_000),
    ("$100B", 100_000_000_000), ("$200B", 200_000_000_000), ("$500B", 500_000_000_000),
    ("$1T", 1_000_000_000_000), ("$2T", 2_000_000_000_000),
    ("$5T", 5_000_000_000_000), ("$10T", 10_000_000_000_000),
]
MARKET_CAP_LABELS = [label for label, _ in MARKET_CAP_OPTIONS]
MARKET_CAP_VALUE_BY_LABEL = dict(MARKET_CAP_OPTIONS)

# Defaults for every filter — also what the form resets to via
# st.session_state on first load.
DEFAULT_FILTERS = {
    # $100B+ (2026-08-27, the explicit default) — well above the
    # $10B Large Cap floor (classify_market_cap() in
    # recommendation_logic.py), i.e. mega/large-cap only by default.
    "cap_range": ("$100B", "$10T"),
    # 2.0 (2026-08-27, the explicit default) — deliberately looser
    # than "Strong Buy only" (≤1.5) so Buy-rated stocks show up too.
    "rating_threshold": 2.0,
    # 50, not SMA_WINDOW_DAYS (100) — 100 is still the locked-in default
    # for the scan's OWN baseline scoring (recommendation_logic.py,
    # unchanged), but it's no longer one of the two picker options
    # (SMA_WINDOW_OPTIONS = [50, 200]) since review narrowed the slicer
    # itself — this just needs to be A VALID option, not necessarily
    # the same number.
    "sma_window": 50,
    "weights": (COMPOSITE_WEIGHT_RECENT_AVG, COMPOSITE_WEIGHT_PEAK, COMPOSITE_WEIGHT_TARGET),
    "composite_cutoff": COMPOSITE_UPSIDE_THRESHOLD_PCT,
}


def filters_to_query_params(filters: dict) -> dict:
    """
    Serialise the APPLIED filters into URL query params, omitting
    anything still at its default so the plain URL stays clean until
    something is actually changed (2026-08-27).

    Weights are stored as whole percentages ("50-25-25") rather than the
    normalised floats they are internally — a URL a human might look at
    shouldn't read "0.5-0.25-0.25".
    """
    params: dict[str, str] = {}
    if filters["cap_range"] != DEFAULT_FILTERS["cap_range"]:
        params["cap"] = f"{filters['cap_range'][0]}-{filters['cap_range'][1]}"
    if filters["rating_threshold"] != DEFAULT_FILTERS["rating_threshold"]:
        params["rating"] = f"{filters['rating_threshold']:.1f}"
    if filters["sma_window"] != DEFAULT_FILTERS["sma_window"]:
        params["sma"] = str(filters["sma_window"])
    if filters["composite_cutoff"] != DEFAULT_FILTERS["composite_cutoff"]:
        params["cut"] = str(filters["composite_cutoff"])
    weights = filters["weights"]
    if tuple(round(w, 4) for w in weights) != tuple(round(w, 4) for w in DEFAULT_FILTERS["weights"]):
        params["w"] = "-".join(f"{w * 100:.0f}" for w in weights)
    return params


def filters_from_query_params() -> dict:
    """
    Rebuild the applied filters from the URL, falling back to
    DEFAULT_FILTERS for anything absent OR invalid.

    This is what makes the browser BACK button, a refresh, and a
    bookmark all restore the same view (2026-08-27: clicking a
    Yahoo/Google link and hitting back "resetted to default again").
    st.session_state alone can't do that — it's per-session, and any
    full page load starts a new session.

    EVERY value here is treated as untrusted input and validated against
    the same ranges the sliders enforce: a query string is trivially
    hand-editable, and a bad value must quietly fall back to the default
    rather than crash the page or smuggle an out-of-range filter past
    the UI.
    """
    filters = dict(DEFAULT_FILTERS)
    qp = st.query_params

    raw_cap = qp.get("cap")
    if raw_cap and "-" in raw_cap:
        low_label, _, high_label = raw_cap.partition("-")
        if low_label in MARKET_CAP_LABELS and high_label in MARKET_CAP_LABELS:
            # Guard against a reversed range (?cap=$10T-$100B), which
            # would otherwise silently match nothing at all.
            if MARKET_CAP_LABELS.index(low_label) <= MARKET_CAP_LABELS.index(high_label):
                filters["cap_range"] = (low_label, high_label)

    try:
        rating = float(qp.get("rating"))
        if 1.0 <= rating <= 5.0:
            filters["rating_threshold"] = round(rating, 1)
    except (TypeError, ValueError):
        pass

    try:
        sma = int(qp.get("sma"))
        if sma in SMA_WINDOW_OPTIONS:
            filters["sma_window"] = sma
    except (TypeError, ValueError):
        pass

    try:
        cutoff = int(qp.get("cut"))
        if 0 <= cutoff <= 60:
            filters["composite_cutoff"] = cutoff
    except (TypeError, ValueError):
        pass

    raw_w = qp.get("w")
    if raw_w:
        try:
            parts = [float(x) for x in raw_w.split("-")]
            total = sum(parts)
            # Same normalisation the sliders use, and the same
            # all-zero guard — three zeroes would divide by zero.
            if len(parts) == 3 and all(p >= 0 for p in parts) and total > 0:
                filters["weights"] = tuple(p / total for p in parts)
        except ValueError:
            pass

    return filters

if "applied_filters" not in st.session_state:
    # Seeded FROM THE URL, not straight from DEFAULT_FILTERS — that's
    # what survives a full page load (back button, refresh, bookmark).
    st.session_state.applied_filters = filters_from_query_params()

# Scan is loaded BEFORE the header so the nav strip can carry the
# scan timestamp as its right-hand meta line, the way the Option 3
# mockup did — rather than as a separate caption stacked underneath.
scan = load_scan_results()
all_results = scan.get("all_results", []) if scan else []

if scan is not None:
    scan_time = datetime.fromisoformat(scan["scan_timestamp_utc"])
    # Year dropped and kept to ONE line deliberately — see the nav
    # layout note below for why the meta can't be two lines.
    # Count taken from the rows we ACTUALLY show, not from the scan's
    # own `tickers_scanned` metadata (2026-08-27: "do we have 503
    # tickers? even after we merged the companies that have more than one
    # ticker like goog and googl?" — no, and the header was lying).
    #
    # `tickers_scanned` records how many the scan fetched, which is 503:
    # the S&P 500's three dual-class duplicates are still in the saved
    # file, and load_scan_results() filters them out afterwards. Reading
    # len(all_results) means this number can never disagree with the
    # universe on screen, including on the day a scan predates a change
    # to the exclusion list.
    scan_meta = (
        f"Last scan {scan_time.strftime('%d %b, %H:%M UTC')} · "
        f"{len(all_results)} tickers"
    )
else:
    scan_meta = "No scan data yet"

# --- Brand header --------------------------------------------------------
# Replaces a 44px emoji st.title (2026-08-27: reviewed the built page
# against the Option 3 mockup review picked, and the emoji title plus a
# 144px yellow disclaimer slab were most of why it still read as a
# script's output instead of a product). The mark is three CSS bars
# rather than the mockup's <svg>, which Streamlit sanitizes away.
#
# Laid out as COLUMNS rather than one st.html block so the Methodology
# link can live in the nav row itself (2026-08-27: sitting alone
# on its own row below, it was "floating like an orphan" — and it was
# genuinely centred, measured at 0px misalignment, so the problem was
# placement, not alignment). A nav link belongs in the nav.
#
# It stays an st.page_link rather than an <a> in the markup: an anchor
# does a full browser reload, page_link navigates client-side and keeps
# scroll position and session state.
with st.container(key="navrow"):
    brand_col, meta_col, nav_link_col = st.columns([2, 5, 1], vertical_alignment="center")
    with brand_col:
        st.html(
            f'<div class="vg-brand">'
            f'<div class="vg-mark"><span style="height:8px"></span>'
            f'<span style="height:13px"></span><span style="height:18px"></span></div>'
            f'<div class="vg-wordmark">{APP_NAME}</div></div>'
        )
    with meta_col:
        # ONE line, not two (2026-08-27). As a two-line block the meta
        # was taller than the brand and the Methodology link either
        # side of it, so vertical centring put the link level with the
        # GAP BETWEEN the two lines — every element measured centred to
        # within 1px, yet it read as misaligned because the link lined
        # up with no actual text. One line makes the row genuinely one
        # line, and the alignment problem stops existing.
        st.html(f'<div class="vg-nav-meta">Daily Equity Recommendations · {scan_meta}</div>')
    with nav_link_col:
        with st.container(key="methodology-link"):
            st.page_link("pages/1_Methodology.py", label="Methodology")

# NOTE: the one-line "Data via Yahoo Finance · Not financial advice ·
# For personal research only" strip that used to sit here was removed
# (2026-08-27: "is this not at the bottom as well? do we want to
# keep it both at the top and bottom?"). It was a strict subset of the
# footer disclaimer at the end of this file, so it was saying the same
# thing twice and costing a row at the top of the page. The FULL text
# still appears in the footer — nothing was weakened, just de-duplicated.

# --- Filters, at the top of the page, as a FORM (2026-08-27: -----
# "let user complete all options and then click submit... dont execute
# with every change") — st.form() is Streamlit's built-in mechanism for
# exactly this: widgets INSIDE a form don't trigger a rerun (and so
# don't recompute anything) until the form's own submit button is
# clicked. Everything a user drags before clicking Apply is just a
# pending, uncommitted position — nothing downstream reacts to it.
with st.form("filters_form"):

    # Every widget below has an EXPLICIT, STATIC `key=` (2026-08-27,
    # fixing a real bug: two of them — the SMA weight and "min upside
    # to SMA" sliders — had labels like f"{sma_window_input}-day avg",
    # embedding the moving-average window's CURRENT value. Streamlit
    # auto-generates a widget's identity from its label (among other
    # args) when no explicit key is given — a well-documented Streamlit
    # gotcha — so whenever the window changed, those two widgets were
    # silently treated as BRAND NEW widgets on that rerun and reset to
    # their last-committed value, discarding whatever the user had just
    # dragged them to. That's exactly what "sometimes don't apply" was:
    # change the window and adjust a weight in the same pass, and the
    # weight change vanished. A static key makes a widget's identity
    # independent of its label text, so the dynamic label (still nice —
    # it shows which window the weight applies to) is now safe to keep.

    # Row 1: four single-control filters, evenly matched heights — was
    # a lopsided 5-column row (2 sparse columns next to 2 columns of 3
    # stacked sliders each), which read as bulky, uneven whitespace
    # (2026-08-27: "very clunky bulky feel"). Splitting into
    # this row plus a second row of two evenly-matched 3-slider columns
    # (below) removes the dead space instead of just shrinking widgets.
    # BOTH rows use the identical column grid — a label column then four
    # equal slots (2026-08-27: "lets find a way to have the top
    # row sliders also beside filters not under it. make everything
    # uniform, font size, slider length etc"). Same ratios in both rows
    # is what guarantees every slider is exactly the same width; the
    # earlier layout had row 1 across 4 columns and row 2 across 3, so
    # the top sliders were unavoidably longer.
    # Four equal slots per row, no label column (2026-08-27:
    # "lets drop filters and composite upside weights as well"). Row 2
    # keeps the same 4-slot grid with the submit button in the last
    # slot, so both rows' sliders stay identical in width and aligned
    # to the same x positions.
    FILTER_ROW_RATIOS = [1, 1, 1, 1]

    row1_col1, row1_col2, row1_col3, row1_col4 = st.columns(
        FILTER_ROW_RATIOS, vertical_alignment="center"
    )

    with row1_col1:
        cap_range_input = st.select_slider(
            "Market cap range",
            options=MARKET_CAP_LABELS,
            value=st.session_state.applied_filters["cap_range"],
            key="filt_cap_range",
        )

    with row1_col2:
        # Back to a plain slider (2026-08-27) — briefly tried as 5
        # rating-bucket checkboxes in a multiselect dropdown, reverted
        # after seeing it in practice (the dropdown's box didn't match
        # the clean single-line sliders around it).
        rating_threshold_input = st.slider(
            "Max analyst rating",
            min_value=1.0, max_value=5.0,
            value=st.session_state.applied_filters["rating_threshold"], step=0.1,
            key="filt_rating_threshold",
            help=(
                "This is Yahoo's aggregate rating — the average of every "
                "covering analyst's individual call, each coded onto a "
                "1–5 scale:\n\n"
                "**1 = Strong Buy**\n\n"
                "**2 = Buy**\n\n"
                "**3 = Hold**\n\n"
                "**4 = Sell**\n\n"
                "**5 = Strong Sell**\n\n"
                "Lower is more bullish — a *higher* number here is "
                "*worse*, easy to get backwards. A stock's aggregate "
                "rating must be at or below this slider's value to "
                "qualify."
            ),
        )

    with row1_col3:
        sma_window_input = st.select_slider(
            "Moving-avg (days)",
            options=SMA_WINDOW_OPTIONS,
            value=st.session_state.applied_filters["sma_window"],
            key="filt_sma_window",
        )

    with row1_col4:
        composite_cutoff_input = st.slider(
            "Min Composite Upside %",
            min_value=0, max_value=60,
            value=st.session_state.applied_filters["composite_cutoff"], step=1,
            key="filt_composite_cutoff",
        )

    # Row 2: the 3 weight sliders side by side, not stacked (2026-08-27,
    # "make the composite upside weights next to each other...
    # horizontal" — also removed the individual min-upside sliders
    # entirely, which used to sit in a second column here).
    # Rendered as html with the same class as the "Filters" panel
    # heading rather than st.markdown("**...**") — as bold markdown it
    # was a <strong> in a <p>, so the panel-heading CSS (scoped to
    # h2/h3) skipped it and it stayed 16px while "Filters" shrank.
    # The weights label, its three sliders AND the submit button all share
    # ONE row (2026-08-27: "the weights scale is too long. we can
    # make it shorter and put it beside the composite upside weights
    # header... apply filter should be just a button with a symbol").
    #
    # This removes two whole rows from the panel — the label had its own
    # full-width row above the sliders (the wide empty gap flagged in review),
    # and the button had another below them. Narrower columns also make
    # each weight slider shorter, which was the other half of the ask.
    w_col1, w_col2, w_col3, w_submit = st.columns(
        FILTER_ROW_RATIOS, vertical_alignment="center"
    )
    prev_w_avg, prev_w_peak, prev_w_target = st.session_state.applied_filters["weights"]

    def _to_step5(weight: float) -> int:
        """
        Weight as a whole percentage SNAPPED to the slider's 5-point step.

        Needed because the stored weights are NORMALISED floats, so they
        don't always land on a multiple of 5 when scaled up: a URL of
        ?w=1-1-1 normalises to 0.3333 each, i.e. 33 — not a valid position
        on a step=5 slider. Snapping the seed keeps the widget's starting
        value legal no matter what produced the weights.
        """
        return int(round(weight * 100 / 5) * 5)
    with w_col1:
        w_avg_raw = st.slider(f"{sma_window_input}-day avg", 0, 100, _to_step5(prev_w_avg), step=5, key="filt_w_avg")
    with w_col2:
        w_peak_raw = st.slider("52-week high", 0, 100, _to_step5(prev_w_peak), step=5, key="filt_w_peak")
    with w_col3:
        w_target_raw = st.slider("Analyst target", 0, 100, _to_step5(prev_w_target), step=5, key="filt_w_target")
    with w_submit:
        # An arrow rather than "Apply Filters". `help` is kept here (unlike
        # the cards' bare "+") because a lone arrow inside a form gives no
        # hint that it COMMITS the settings — and nothing on the page
        # updates until it's pressed.
        submitted = st.form_submit_button(
            "→", type="primary", help="Apply filters"
        )

if submitted:
    weight_total = w_avg_raw + w_peak_raw + w_target_raw
    if weight_total == 0:
        # All three dragged to 0 — fall back to the locked-in defaults
        # rather than dividing by zero.
        new_weights = (COMPOSITE_WEIGHT_RECENT_AVG, COMPOSITE_WEIGHT_PEAK, COMPOSITE_WEIGHT_TARGET)
    else:
        # Normalized so the three sliders only need to reflect RELATIVE
        # importance, not painstakingly add up to exactly 100 — e.g.
        # 50/50/50 means "equal weight," same as 33/33/33.
        new_weights = (w_avg_raw / weight_total, w_peak_raw / weight_total, w_target_raw / weight_total)
    st.session_state.applied_filters = {
        "cap_range": cap_range_input,
        "rating_threshold": rating_threshold_input,
        "sma_window": sma_window_input,
        "weights": new_weights,
        "composite_cutoff": composite_cutoff_input,
    }
    # Mirror the applied filters into the URL. Assigning to
    # st.query_params REPLACES the whole query string, so anything back
    # at its default drops out and the URL stays clean.
    st.query_params.from_dict(filters_to_query_params(st.session_state.applied_filters))

# Everything below reads ONLY from st.session_state.applied_filters —
# never from the form's raw widget variables above — so dragging a
# slider without clicking "Apply Filters" changes nothing on the page,
# even across an unrelated rerun (e.g. clicking a heatmap box).
af = st.session_state.applied_filters
cap_range = (MARKET_CAP_VALUE_BY_LABEL[af["cap_range"][0]], MARKET_CAP_VALUE_BY_LABEL[af["cap_range"][1]])
rating_threshold = af["rating_threshold"]
sma_window, weights, composite_cutoff = af["sma_window"], af["weights"], af["composite_cutoff"]
# Dollar signs escaped (\$) — a PAIR of unescaped $ in Streamlit
# markdown gets read as LaTeX math mode (the exact same bug already
# hit and documented elsewhere in this project), and "$10B" next to
# "$10T" is exactly that pair.
cap_range_display = f"\\{af['cap_range'][0]}–\\{af['cap_range'][1]}"

if scan is not None:
    # Recompute EVERY scanned ticker's evaluation against the currently
    # APPLIED filters, once per page run. qualifying_results (rating +
    # cap range + composite cutoff all passed) drives BOTH the heatmap
    # and the Focus List, so they always show the same set. Computed
    # BEFORE the "Showing:" caption below (2026-08-27: wants the
    # match count right there every time Apply Filters is clicked, not
    # just further down at the Focus List).
    live_results = [
        compute_live_evaluation(
            r, sma_window, weights, rating_threshold, composite_cutoff, cap_range
        )
        for r in all_results
    ]
    qualifying_results = sorted(
        (r for r in live_results if r["recommended"]),
        key=lambda r: r.get("composite_upside_pct") or 0,
        reverse=True,
    )
    match_count_display = f"{len(qualifying_results)} tickers"
else:
    match_count_display = "No scan available yet"

# One line under the filter panel, not two (2026-08-27). The bold
# "**N tickers** currently match." sentence that used to sit here was
# removed: the same count was ALSO repeated under the Opportunity Map
# heading, and between the two of them plus a divider the gap between
# the filters and the map was mostly empty space. The count now appears
# once, on the map's own caption where it describes what you're looking
# at.
st.caption(
    f"Showing: {cap_range_display} market cap · "
    f"rating ≤ {rating_threshold:.1f} · {sma_window}-day avg weighted "
    f"{weights[0]*100:.0f}/{weights[1]*100:.0f}/{weights[2]*100:.0f} · "
    f"Composite Upside ≥ {composite_cutoff}%"
)

st.divider()

if scan is None:
    st.info("No scan has run yet. Run `run_daily_scan.py` first to generate results.")
else:
    # --- One heatmap: Composite Upside %, the same metric that drives ----
    # the focus list below it (2026-08-27 — was 4 separate slices across
    # a tab; simplified to the one number that actually matters here).
    st.subheader("Opportunity Map")
    # Count folded into the map's own one-line caption. The old version
    # restated every filter here ("Filtered by the panel above (rating
    # ≤ 2.0, $100B–$10T market cap, ...)") — word-for-word what the
    # "Showing:" caption above the divider already says, so it was cut
    # rather than repeated.
    st.caption(
        f"{match_count_display} · Box size = market cap · "
        f"Color = Composite Upside %"
    )
    render_heatmap(qualifying_results, "composite_upside_pct", "Composite Upside", "heatmap_main")

    st.divider()

    # --- Today's Focus List — the tickers that actually clear the bar ----
    st.subheader("Today's Focus List")
    # Same one-line caption shape as the Opportunity Map's, so the two
    # sections read as a pair rather than each announcing the count in
    # its own wording.
    st.caption(f"{match_count_display} · Open any card for full detail and the price scale")
    if not qualifying_results:
        st.info("Nothing clears your current filters — try loosening a slider in the sidebar.")
    else:
        # 3-across grid (2026-08-27, back to the Option 3 mockup's card
        # layout after a spell as full-width rows). A FRESH st.columns(3)
        # per row of three, rather than one set of 3 columns fed all the
        # tickers: with a single set, Streamlit stacks items down each
        # column independently (col 0 gets items 0,3,6...), so any card
        # that renders a pixel taller than its neighbours knocks every
        # card below it out of horizontal alignment. Chunking keeps each
        # visual row aligned.
        for i in range(0, len(qualifying_results), 3):
            for col, r in zip(st.columns(3), qualifying_results[i:i + 3]):
                with col:
                    render_focus_card(r, sma_window, weights)

# The bottom "See full methodology →" link was removed (2026-08-27) —
# the header link above covers it, and the emoji icon it carried was
# the last one left on the page.

# The full disclaimer text, moved here from a yellow st.warning slab
# that used to sit above the page title (2026-08-27). It's the same
# wording — demoted in prominence, not softened or deleted, and the
# one-line version still sits under the header where it's seen first.
st.html(
    '<div class="vg-footer">'
    "<b>Data reliability:</b> this tool relies on <code>yfinance</code>, an "
    "unofficial/unsupported way of reading Yahoo Finance data — not guaranteed "
    "accurate, complete, or continuously available.<br>"
    "<b>Not financial advice:</b> this tool encodes personal rules/logic in "
    "software. It is not professional investment advice, not from a licensed "
    "advisor, and should be used at your own risk."
    "</div>"
)
