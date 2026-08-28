"""
Vantage — main page.

Streamlit entry point. Reads the results of the most recent scan for
the selected market (written by run_daily_scan.py to
output/latest_scan_<market>.json) and renders them; it never fetches
market data itself, so every filter is arithmetic over already-loaded
numbers and responds instantly.

Page structure, top to bottom:

    header          brand, scan timestamp, link to the Methodology page
    filter form     market cap, analyst rating, moving-average window,
                    minimum Composite Upside %, and the three weights.
                    Gated behind Apply, so nothing recomputes mid-drag.
    Opportunity Map treemap-style grid; tile size = market-cap rank,
                    colour = Composite Upside %. Display only.
    Focus List      a card per qualifying company, with a "+" that opens
                    the full price scale in a modal.
    footer          data-source and not-financial-advice notices

The map and the Focus List consume the same computed list, so they can
never show different sets of tickers for the same filters.

pages/1_Methodology.py is a second Streamlit page explaining the scoring
in plain language. See DESIGN_DOC.md for architecture and rationale.
"""

import json
from pathlib import Path
from datetime import datetime, timezone

import streamlit as st

import analytics
from sp500_tickers import DUPLICATE_SHARE_CLASSES_TO_DROP
from markets import MARKETS, DEFAULT_MARKET_ID
from recommendation_logic import (
    COMPOSITE_UPSIDE_THRESHOLD_PCT,
    SMA_WINDOW_DAYS,
    SMA_WINDOW_OPTIONS,
    COMPOSITE_WEIGHT_RECENT_AVG,
    COMPOSITE_WEIGHT_PEAK,
    COMPOSITE_WEIGHT_TARGET,
)
from theme import (
    APP_NAME,
    inject_theme_css,
    render_brand_mark,
    POSITIVE_COLOR,
    NEGATIVE_COLOR,
    CAP_TIER_COLORS,
)

OUTPUT_DIR = Path(__file__).parent / "output"
MAX_BANNER_NAME_LENGTH = 40


# layout="wide" gives the heatmap and focus-list cards real horizontal
# room — part of the "Minimal Data-First" visual direction review
# picked.
st.set_page_config(page_title=f"{APP_NAME} — Daily Scan", page_icon="📈", layout="wide")
# Must run immediately after set_page_config, before any other widget —
# see theme.py for why.
inject_theme_css()

# ?analytics=on shows the usage dashboard INSTEAD OF the normal page —
# checked before any scan loading or market resolution, since the
# dashboard doesn't need either. See analytics.py for what this tracks
# and why it's a hand-rolled counter rather than a third-party package.
if analytics.is_dashboard_requested():
    analytics.render_dashboard()
    st.stop()
analytics.track_page_view()


def load_scan_results(market) -> dict | None:
    """Read the most recent scan results for one market. Returns None if
    that market hasn't been scanned yet."""
    output_file = OUTPUT_DIR / market.scan_output_file
    if not output_file.exists():
        return None
    with open(output_file) as f:
        scan = json.load(f)

    # The dual-class dedup (GOOGL/FOX/NWS) is specific to the S&P 500's
    # own index quirks — it has no meaning for a market that doesn't
    # have those tickers, so it's only applied for that one market
    # rather than unconditionally on every scan file.
    if market.id == "sp500":
        for key in ("all_results", "recommendations"):
            scan[key] = [r for r in scan[key] if r["ticker"] not in DUPLICATE_SHARE_CLASSES_TO_DROP]

    return scan


def truncate_company_name(name: str, max_length: int = MAX_BANNER_NAME_LENGTH) -> str:
    if len(name) <= max_length:
        return name
    return name[:max_length].rstrip(", ") + "…"


def clean_company_name(name: str | None) -> str:
    """Normalise a company name for display.

    The data source returns some names with a trailing article, e.g.
    "Home Depot, Inc. (The)". The article is moved to the front rather
    than dropped, so the name still reads correctly.
    """
    if not name:
        return ""
    if name.endswith(" (The)"):
        return "The " + name[: -len(" (The)")]
    return name


def build_external_links_html(r: dict, size_class: str = "") -> str:
    """Return Yahoo and Google Finance links as small brand-marked chips.

    `size_class` is an optional extra CSS class ("vg-ext-sm" for the
    smaller variant used on cards).

    Plain <a> tags rather than st.link_button, so they can sit inline
    inside st.html markup. Brand letters rather than logos, because
    st.html() strips <svg> and an external <img> would add a network
    dependency.

    The Google Finance link is omitted for any ticker whose exchange
    isn't mapped (NASDAQ, NYSE, NSE and BSE).
    """
    yahoo_url = f"https://finance.yahoo.com/quote/{r['ticker']}"
    cls = f"vg-ext {size_class}".strip()
    html = (
        f'<a class="{cls} vg-ext-y" href="{yahoo_url}" target="_blank" '
        f'rel="noopener" title="Open {r["ticker"]} in Yahoo Finance">Y!</a>'
    )
    google_exchange = r.get("google_finance_exchange")
    if google_exchange:
        # Google Finance's own URL scheme is SYMBOL:EXCHANGE with the
        # BARE symbol — unlike Yahoo above, it does NOT want yfinance's
        # own exchange suffix (".NS", ".BO") included. Verified directly:
        # "TRENT.NS:NSE" resolves to a generic, unrecognised page (its
        # <title> just echoes the URL back), while "TRENT:NSE" resolves
        # to the real listing. US tickers have no such suffix, so this
        # bug was invisible until a market with suffixed tickers existed.
        bare_symbol = r["ticker"].split(".")[0]
        google_url = f"https://www.google.com/finance/quote/{bare_symbol}:{google_exchange}"
        html += (
            f'<a class="{cls} vg-ext-g" href="{google_url}" target="_blank" '
            f'rel="noopener" title="Open {r["ticker"]} in Google Finance">G</a>'
        )
    return html


def build_price_scale_html(r: dict, sma_window: int, market) -> str:
    """Render the horizontal price scale used in the detail modal.

    Plots five reference points on a single number line: 52-week low,
    the moving average for `sma_window`, the current price, the analyst
    median target, and the 52-week high.

    Built from absolutely-positioned <div>s rather than SVG, because
    st.html() strips <svg> elements entirely.

    Layout rules:
    - Each label stacks its price above its percentage, keeping labels
      narrow so neighbouring points are less likely to collide.
    - Labels alternate above and below the track, so adjacent points can
      never overlap. Points two apart can still land on the same side,
      so same-side labels are pushed to a minimum horizontal gap; the
      MARKER always stays at its true value and only the label moves.
      A connector line is drawn whenever the two separate enough to be
      mispaired by eye.
    - Labels within 12% of either end anchor to that edge instead of
      centring, so a wide value can only grow inward.
    - "Now" is the focal point, distinguished by contrast rather than
      size: the only near-black value, heavier weight, larger marker.
      Colour marks three points (low red, now black, high green); the
      moving average and target stay grey, since their percentages
      already carry green/red.

    The scale is NOT clamped to the 52-week high: an analyst target can
    legitimately sit above it, and clamping would hide exactly the
    signal Composite Upside % exists to catch.

    The moving average's dollar price is not stored anywhere, only its
    upside percentage. It is reconstructed here as the exact inverse of
    compute_upside_pct(): ref = current * (1 + upside / 100).
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
        Cents dropped on the scale ("should we remove
        decimal points?"). Shorter labels are the cheapest way to buy
        horizontal room, and the exact price with cents is already on the
        card. Precision scales with magnitude rather than being dropped
        flat — at $8 the cents ARE the signal, at $733 they're noise.
        """
        if v >= 100:
            return f"{market.currency_symbol}{v:,.0f}"
        if v >= 10:
            return f"{market.currency_symbol}{v:,.1f}"
        return f"{market.currency_symbol}{v:,.2f}"

    neutral = "var(--vg-text-muted)"
    # (label, value, pct, pct suffix, accent colour, value colour, is_hero)
    #
    # third pass on the scale:
    # "Current Price" back to "NOW". The long label was widening the
    #   left cluster on tickers where price sits near the 52-week low;
    #   the hero styling (largest, boldest) is what makes it findable,
    #   not the label text, so the short form costs nothing.
    # The $ VALUE is now coloured too, not just the label word — with
    #   every value in the same near-black, the hero's larger size was
    #   the only differentiator and it wasn't possible to tell it was bigger.
    # Every value renders at the same size. "Now" is distinguished by
    # CONTRAST, not scale:
    #   - it is the only near-black value; the moving average and analyst
    #     target are muted gray, which is what leaves black distinctive
    #   - heavier weight (800 vs 700)
    #   - a larger marker (13px vs 9px)
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

        # Labels near an edge anchor to it rather than centring, so a
        # wide value can only ever grow inward. render_lpos tracks where
        # the label ACTUALLY renders (0 or 100 once anchored, not the
        # raw lpos it was anchored FROM) — the connector below must
        # compare against this, not lpos, or a label whose true
        # position sits just inside the 10%/90% threshold (near an
        # edge but not pinned to it) silently jumps to the literal edge
        # with no line bridging the gap back to its own marker.
        if lpos <= 10:
            anchor = "left:0; transform:none; text-align:left;"
            render_lpos = 0.0
        elif lpos >= 90:
            anchor = "right:0; left:auto; transform:none; text-align:right;"
            render_lpos = 100.0
        else:
            anchor = f"left:{lpos:.2f}%; transform:translateX(-50%); text-align:center;"
            render_lpos = lpos
        offset = "bottom:56px;" if i % 2 == 0 else "top:56px;"

        # Connector, only when the label had to move far enough that the
        # eye would otherwise mis-pair it with the wrong marker.
        if abs(render_lpos - mpos) > 1.5:
            left, right = sorted((mpos, render_lpos))
            vert = "bottom:calc(50% + 6px); height:14px;" if i % 2 == 0 else "top:calc(50% + 6px); height:14px;"
            parts.append(
                f'<div style="position:absolute; left:{left:.2f}%; width:{right - left:.2f}%; '
                f'{vert} border-top:1px solid var(--vg-border); z-index:1;"></div>'
            )

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
def show_detail_dialog(r: dict, sma_window: int, weights: tuple[float, float, float], market) -> None:
    """Open the full detail view for one ticker as a modal.

    Shows a single header line (ticker, market cap, company, external
    links) and the full-width price scale.

    Nothing else is included on purpose: the close, 52-week high,
    analyst target and their upsides are all points ON the scale, so
    listing them underneath would repeat the same numbers.

    A modal rather than an in-card expander because the scale needs more
    width than a third of the page.

    `weights` is accepted for call-site symmetry but is not needed for
    display.
    """
    cap_tier = r.get("market_cap_tier")
    tier_color = CAP_TIER_COLORS.get(cap_tier, "#c3cad1")
    company = truncate_company_name(clean_company_name(r.get("company_name")), max_length=52)

    links = build_external_links_html(r)

    st.html(
        f'<div class="vg-modal-head">'
        f'<span class="vg-modal-ticker">{r["ticker"]}</span>'
        f'<span class="vg-cap-tag" style="background:{tier_color};">'
        f'{market.format_market_cap(r.get("market_cap"))}</span>'
        f'<span class="vg-modal-co">{company}</span>'
        f'<span class="vg-modal-links">{links}</span>'
        f"</div>"
    )
    st.html(build_price_scale_html(r, sma_window, market))


def render_focus_card(r: dict, sma_window: int, weights: tuple[float, float, float], market) -> None:
    """Render one card in the Focus List grid.

    Shows the ticker, company, market-cap tier and value, current price,
    Composite Upside % as a pill, a 52-week range bar, and the three
    upside components that feed the composite.

    The range bar is kept visually separate from those three figures:
    they measure room left to gain, while "% above the low" measures
    distance already travelled, and grouping them would imply a fourth
    upside to weigh alongside the others.

    The price scale is deliberately not on the card — it needs more
    width than a third of the page, so it lives in the "+" modal
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
    # and high, plus how far it has run from the low (
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
            f'{cap_tier or "Cap n/a"} · {market.format_market_cap(r.get("market_cap"))}</span>'
            f'<span class="vg-card-links">{build_external_links_html(r, "vg-ext-sm")}</span></div>'
            f'<div class="vg-card-price">{market.currency_symbol}{r["most_recent_close"]:,.2f}</div>'
            f"{range_html}"
            f'<div class="vg-card-stats">'
            f'{_stat(f"{sma_window}D Avg", r.get("upside_to_recent_avg_pct"))}'
            f'{_stat("52W High", r.get("upside_to_52w_high_pct"))}'
            f'{_stat("Target", r.get("upside_to_target_pct"))}'
            f"</div>"
        )
        # Rendered last in the card's flow, but CSS positions it into the
        # top-right corner beside the upside pill.
        #
        # Streamlit buttons are block elements and cannot be nested into
        # the st.html markup above, so the card acts as the positioning
        # context and the button is placed absolutely inside it. It stays
        # a real st.button with click handling intact; only its position
        # is CSS. It carries no label text and no `help` tooltip — review
        # wants "just a + sign"; a "+" in a card's corner is a
        # well-understood affordance on its own.
        if st.button("+", key=f"detailbtn-{r['ticker']}"):
            analytics.track_card_opened(r["ticker"])
            show_detail_dialog(r, sma_window, weights, market)


def _round_pcts_to_100(fractions: tuple[float, float, float]) -> tuple[int, int, int]:
    """
    Three already-normalised fractions (summing to 1.0) as whole
    percentages that ALWAYS sum to exactly 100 — rounding each
    independently (e.g. three values at 33.3%) can land on 99 or 101,
    which defeats the entire point of showing this to a user who's
    specifically checking that the weights add up. Uses the standard
    "largest remainder" method: floor every value, then hand the
    leftover points to whichever values lost the most to flooring.
    """
    exact = [f * 100 for f in fractions]
    floored = [int(e) for e in exact]
    remainder = 100 - sum(floored)
    by_leftover = sorted(range(3), key=lambda i: exact[i] - floored[i], reverse=True)
    for i in range(remainder):
        floored[by_leftover[i]] += 1
    return tuple(floored)


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
    # red → green (review proposed red for the weakest
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
    """Render the Opportunity Map as a CSS grid.

    Tile size follows market-cap rank; tile colour follows `color_field`
    (Composite Upside %). Expects an already-filtered list, so the map
    and the Focus List always agree.

    Display only — no hover, click or zoom.

    Tile sizes come from a rank tier table rather than area proportional
    to market cap: the index's cap distribution is top-heavy enough that
    a truly proportional map lets a few tiles swallow the grid.

    Colour endpoints are the 5th/95th percentile of the visible set, not
    its raw min/max. With raw endpoints a single outlier compresses
    everything else into one shade; clamping lets outliers saturate
    while the rest of the field spreads across the ramp. The legend
    still reports the true min and max.
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
    # raw min/max. With raw endpoints a single outlier
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
    """Re-score one scan result against the currently applied filters.

    Returns a NEW dict — a shallow copy of `r` with composite_upside_pct,
    upside_to_recent_avg_pct, recommended and skip_reason recomputed for
    the given weights, moving-average window and thresholds.

    Pure arithmetic over values already loaded from the saved scan, with
    no API calls, so it is cheap enough to run for every ticker on every
    interaction.

    A stock qualifies when its aggregate analyst rating is at or below
    `rating_threshold`, its market cap falls inside `cap_range`, and its
    composite upside meets `composite_cutoff`.

    `recommended` and `skip_reason` are recomputed rather than reused so
    the badge and the "not a current pick" message always describe the
    current filters, not the fixed values saved at scan time.
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


def default_filters_for(market) -> dict:
    """Default filter values for one market — what the form resets to on
    first load, or whenever the selected market changes.

    Only cap_range varies by market (it's expressed in that market's own
    label set, e.g. "$100B" vs "₹1,00,000 Cr" — see markets.py). The
    other four filters are market-agnostic concepts, so they keep the
    same defaults regardless of which universe is selected.
    """
    return {
        "cap_range": market.default_cap_range,
        # 2.0 — deliberately looser than "Strong Buy only" (≤1.5) so
        # Buy-rated stocks show up too.
        "rating_threshold": 2.0,
        # 50, not SMA_WINDOW_DAYS (100) — 100 is still the locked-in
        # default for the scan's OWN baseline scoring
        # (recommendation_logic.py, unchanged), but it's no longer one
        # of the two picker options (SMA_WINDOW_OPTIONS = [50, 200])
        # since the slicer itself was narrowed — this just needs to be
        # A VALID option, not necessarily the same number.
        "sma_window": 50,
        "weights": (COMPOSITE_WEIGHT_RECENT_AVG, COMPOSITE_WEIGHT_PEAK, COMPOSITE_WEIGHT_TARGET),
        "composite_cutoff": COMPOSITE_UPSIDE_THRESHOLD_PCT,
    }


def filters_to_query_params(filters: dict, market) -> dict:
    """Serialise applied filters into URL query parameters.

    Only values that differ from that market's own defaults are
    included, so the URL stays clean until something is actually
    changed. The market itself is written separately by the caller
    (it's a bigger switch than a filter tweak, and needs to be readable
    before any of the filter values can even be interpreted).

    Weights are written as whole percentages ("50-25-25") rather than
    the normalised floats used internally.
    """
    defaults = default_filters_for(market)
    params: dict[str, str] = {}
    if filters["cap_range"] != defaults["cap_range"]:
        params["cap"] = f"{filters['cap_range'][0]}-{filters['cap_range'][1]}"
    if filters["rating_threshold"] != defaults["rating_threshold"]:
        params["rating"] = f"{filters['rating_threshold']:.1f}"
    if filters["sma_window"] != defaults["sma_window"]:
        params["sma"] = str(filters["sma_window"])
    if filters["composite_cutoff"] != defaults["composite_cutoff"]:
        params["cut"] = str(filters["composite_cutoff"])
    weights = filters["weights"]
    if tuple(round(w, 4) for w in weights) != tuple(round(w, 4) for w in defaults["weights"]):
        params["w"] = "-".join(f"{w * 100:.0f}" for w in weights)
    return params


def filters_from_query_params(market) -> dict:
    """Rebuild applied filters from the URL, falling back to `market`'s
    own defaults.

    This is what lets the browser back button, a refresh and a bookmark
    restore the same view; st.session_state alone cannot, since it is
    per-session and any full page load starts a new one.

    Every value is treated as untrusted input and validated against the
    same ranges the sliders enforce — a query string is trivially
    editable, so anything invalid falls back to the default rather than
    reaching the filtering logic. Includes guards for a reversed market
    cap range, which would otherwise match nothing, and for all-zero
    weights, which would divide by zero.
    """
    filters = default_filters_for(market)
    qp = st.query_params
    cap_labels = [label for label, _ in market.cap_range_options]

    raw_cap = qp.get("cap")
    if raw_cap and "-" in raw_cap:
        low_label, _, high_label = raw_cap.partition("-")
        if low_label in cap_labels and high_label in cap_labels:
            # Guard against a reversed range (?cap=$10T-$100B), which
            # would otherwise silently match nothing at all.
            if cap_labels.index(low_label) <= cap_labels.index(high_label):
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

# Which market is active is resolved BEFORE anything else on the page —
# scan loading, the header, and the filter defaults all depend on it.
# Seeded from the URL (?market=nifty50) so a bookmark or a shared link
# opens on the right universe, same reasoning as applied_filters below.
if "selected_market_id" not in st.session_state:
    url_market_id = st.query_params.get("market")
    st.session_state.selected_market_id = url_market_id if url_market_id in MARKETS else DEFAULT_MARKET_ID
market = MARKETS[st.session_state.selected_market_id]

if "applied_filters" not in st.session_state:
    # Seeded FROM THE URL, not straight from the market's defaults —
    # that's what survives a full page load (back button, refresh,
    # bookmark).
    st.session_state.applied_filters = filters_from_query_params(market)

# Per-market filter memory, keyed by market id — lets switching back to
# a market you've already customized THIS session restore what you set
# there, instead of resetting to that market's defaults every time. Kept
# separate from applied_filters (the CURRENTLY active market's filters)
# and only ever read/written for the market whose own values they are —
# never carried across markets, since a range like "$100B" has no
# meaning translated into another market's own units.
st.session_state.setdefault("per_market_filters", {})

# Scan is loaded BEFORE the header so the nav strip can carry the
# scan timestamp as its right-hand meta line, the way the Option 3
# mockup did — rather than as a separate caption stacked underneath.
scan = load_scan_results(market)
all_results = scan.get("all_results", []) if scan else []

if scan is not None:
    scan_time = datetime.fromisoformat(scan["scan_timestamp_utc"])
    # Year dropped and kept to ONE line deliberately — see the nav
    # layout note below for why the meta can't be two lines.
    # Count taken from the rows we ACTUALLY show, not from the scan's
    # own `tickers_scanned` metadata ("do we have 503
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
# Replaces a 44px emoji st.title (reviewed the built page
# against the Option 3 mockup review picked, and the emoji title plus a
# 144px yellow disclaimer slab were most of why it still read as a
# script's output instead of a product). The mark is three CSS bars
# rather than the mockup's <svg>, which Streamlit sanitizes away.
#
# TWO rows, not one: the brand alone on its own row, then a second row
# split left (a quiet disclaimer note + link to the full legal-style
# Disclaimer page) / right (scan meta + Methodology link). Added once
# the site started being shared beyond friends — strangers with no
# context need the disclaimer visible without scrolling, but a full
# yellow warning slab (the ORIGINAL header, before it was cut) was
# explicitly what made the page read as amateurish. Splitting the
# disclaimer onto its own quiet row is the middle ground: real
# visibility without reintroducing that look.
#
# The meta/link rows are kept to ONE line each on purpose: as two lines
# a block is taller than its row-mates, and vertical centring then
# aligns a neighbour with the GAP between two lines rather than with
# any text — the exact bug hit once already when this was a single row.
#
# Every page_link (not a plain <a> in the markup) for the same reason:
# an anchor does a full browser reload, page_link navigates client-side
# and keeps scroll position and session state.
with st.container(key="navrow"):
    render_brand_mark()
    disc_text_col, disc_link_col, meta_col, nav_link_col = st.columns(
        [2.5, 1.3, 4, 1.3], vertical_alignment="center"
    )
    with disc_text_col:
        st.html('<div class="vg-nav-disclaimer">Not financial advice</div>')
    with disc_link_col:
        with st.container(key="disclaimer-link"):
            st.page_link("pages/2_Disclaimer.py", label="Full disclaimer")
    with meta_col:
        st.html(f'<div class="vg-nav-meta">{scan_meta}</div>')
    with nav_link_col:
        with st.container(key="methodology-link"):
            st.page_link("pages/1_Methodology.py", label="Methodology")

# NOTE: the one-line "Data via Yahoo Finance · Not financial advice ·
# For personal research only" strip that used to sit here was removed
# ("is this not at the bottom as well? do we want to
# keep it both at the top and bottom?"). It was a strict subset of the
# footer disclaimer at the end of this file, so it was saying the same
# thing twice and costing a row at the top of the page. The FULL text
# still appears in the footer — nothing was weakened, just de-duplicated.

# --- Market selector — deliberately OUTSIDE the filter form -------------
# Switching markets changes the entire universe (and the market-cap
# scale's units), so it reacts immediately rather than waiting behind
# Apply Filters the way a slider tweak does. st.radio outside a form
# reruns the script on every change, same as any plain widget.
market_ids = list(MARKETS.keys())
with st.container(key="filter-tile-market"):
    picked_market_id = st.radio(
        "Market to scan",
        options=market_ids,
        format_func=lambda mid: MARKETS[mid].display_name,
        index=market_ids.index(st.session_state.selected_market_id),
        key="market_selector_widget",
        horizontal=True,
    )
if picked_market_id != st.session_state.selected_market_id:
    analytics.track_market_selected(picked_market_id)
    new_market = MARKETS[picked_market_id]
    # Remember the OLD market's filters before leaving it, so switching
    # back later this session restores them instead of resetting to
    # that market's defaults all over again.
    st.session_state.per_market_filters[st.session_state.selected_market_id] = (
        st.session_state.applied_filters
    )
    st.session_state.selected_market_id = picked_market_id
    # Restore the NEW market's own filters from a previous visit this
    # session if there is one, otherwise its defaults. Never the OLD
    # market's values, carried over — a range expressed in one market's
    # labels ("$100B") has no meaning in another's ("₹ Cr"), so
    # attempting to reuse it would either error or silently mean
    # something different than what the user set it to.
    st.session_state.applied_filters = st.session_state.per_market_filters.get(
        picked_market_id, default_filters_for(new_market)
    )
    # The form widgets below ALSO persist their own value under their
    # own key, independent of applied_filters — st.select_slider in
    # particular would raise an exception on the next render, because
    # its remembered value (the OLD market's cap-range labels) wouldn't
    # exist in the NEW market's `options` list. Deleting these keys
    # makes every widget reseed itself fresh from `value=` instead of
    # reusing a now-invalid remembered one.
    for widget_key in (
        "filt_cap_range", "filt_rating_threshold", "filt_sma_window",
        "filt_composite_cutoff", "filt_weights_range",
    ):
        st.session_state.pop(widget_key, None)
    if picked_market_id == DEFAULT_MARKET_ID:
        st.query_params.pop("market", None)
    else:
        st.query_params["market"] = picked_market_id
    # Restart the script from the top NOW rather than letting execution
    # continue with the just-loaded OLD market's scan data still in
    # `scan`/`all_results` for the rest of this run — st.rerun() is what
    # makes this take effect on a clean pass instead of an inconsistent
    # partial one.
    st.rerun()

# --- Filters, at the top of the page (----
# "let user complete all options and then click submit... dont execute
# with every change") — the actual STOCK LIST/heatmap recompute is
# gated behind st.session_state.applied_filters, only written inside
# `if submitted:` below, so it stays exactly that deliberate regardless
# of what triggers a script rerun above it.
#
# This was originally st.form(), Streamlit's built-in mechanism for
# batching every contained widget's reruns until one submit click —
# switched to a plain container because that batching had a real cost:
# it also froze the Composite Upside weights legend and the slider's
# own 3-color fill, both of which read live widget state, not
# session_state. Dragging a handle moved the handle but the shares/
# colors "did not follow... only changed when I clicked submit." Since
# nothing expensive is gated on the rerun itself — only on
# applied_filters, written once, on click — there was no actual reason
# for every OTHER widget in the panel to be form-batched too.
with st.container(key="filters_panel"):

    # Every widget below has an EXPLICIT, STATIC `key=` (
    # fixing a real bug: two of them — the SMA weight and "min upside
    # to SMA" sliders — had labels like f"{sma_window_input}-day avg",
    # embedding the moving-average window's CURRENT value. Streamlit
    # auto-generates a widget's identity from its label (among other
    # args) when no explicit key is given — a well-documented Streamlit
    # gotcha — so whenever such a value changes, the widget is treated as
    # brand new on that rerun and silently resets to its last-committed
    # value, discarding any uncommitted input. A static key makes a
    # widget's identity independent of its label text, which keeps the
    # dynamic label (useful: it names the window the weight applies to)
    # safe to use.

    # Both rows use the SAME column grid: four equal slots. Row 1 holds
    # the four filters; row 2 holds the three weight sliders plus the
    # submit button in the last slot.
    #
    # Identical ratios in both rows is what makes every slider exactly
    # the same width and aligns the two rows to the same x positions.
    # Uneven column counts between rows would make one row's sliders
    # unavoidably longer than the other's.
    FILTER_ROW_RATIOS = [1, 1, 1, 1]

    row1_col1, row1_col2, row1_col3, row1_col4 = st.columns(
        FILTER_ROW_RATIOS, vertical_alignment="center"
    )

    # Each filter now sits inside its own lightly-bordered tile — a
    # nested st.container(key=...) per column, styled in theme.py the
    # same way every other bordered box in this app is (border-color:
    # var(--vg-border), border-radius: var(--vg-radius)), so row 1 reads
    # as four distinct controls rather than four sliders that just
    # happen to share a row with nothing marking where one ends and the
    # next begins.
    with row1_col1, st.container(key="filter-tile-cap"):
        cap_range_input = st.select_slider(
            "Market cap range",
            options=[label for label, _ in market.cap_range_options],
            value=st.session_state.applied_filters["cap_range"],
            key="filt_cap_range",
            help=(
                "Market capitalization — share price × total shares "
                "outstanding, roughly a company's total value. Only "
                "stocks within this range are considered."
            ),
        )

    with row1_col2, st.container(key="filter-tile-rating"):
        # A plain slider rather than rating-bucket checkboxes: a
        # multiselect's boxed tag container reads as a heavier control
        # than the single-line sliders beside it.
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

    with row1_col3, st.container(key="filter-tile-sma"):
        sma_window_input = st.select_slider(
            "Moving-avg (days)",
            options=SMA_WINDOW_OPTIONS,
            value=st.session_state.applied_filters["sma_window"],
            key="filt_sma_window",
            help=(
                "The average closing price over the last 50 (or 200) "
                "trading days — a standard way to see a stock's recent "
                "typical price, smoothing out day-to-day noise. Used to "
                "check whether today's price has genuinely pulled back, "
                "not just dipped for a day."
            ),
        )

    with row1_col4, st.container(key="filter-tile-cutoff"):
        composite_cutoff_input = st.slider(
            "Min Composite Upside %",
            min_value=0, max_value=60,
            value=st.session_state.applied_filters["composite_cutoff"], step=1,
            key="filt_composite_cutoff",
            help=(
                "Composite Upside % blends three measures of \"room "
                "to grow\" — upside to the moving average, to the "
                "52-week high, and to the analyst price target — into "
                "one score. Only stocks scoring at or above this "
                "minimum are shown. Full formula on the Methodology "
                "page."
            ),
        )

    # Row 2: the Composite Upside weights control + the submit button
    # share one row, same as row 1's filters. Originally three separate
    # 0-100 sliders (moving avg / 52w high / target), each independently
    # normalised afterward — replaced with the two-handle range slider
    # below once a site visitor, on having that normalising step
    # explained to her, asked the obvious follow-up: "if we're
    # normalizing anyway, shouldn't this just BE a 3-way split control?"
    # A widget-level heading also came back for this row specifically
    # (see the slider's own label below) — a site visitor separately
    # called the site owner to say she couldn't tell this row was about
    # weights at all without one, since unlabelled sliders read as more
    # individual filters, same as row 1 above. The heading existed once
    # and was removed for panel height ("make the panel sleeker,
    # minimal"); this is real feedback to bring it back for this row
    # specifically, not to redo that whole round of trimming.
    prev_w_avg, prev_w_peak, prev_w_target = st.session_state.applied_filters["weights"]

    # ONE two-handle range slider instead of three independent 0-100
    # sliders. The old design let each slider go anywhere 0-100 and
    # silently normalised the three afterward ("50/50/50 means equal
    # weight, same as 33/33/33") — technically correct, but a real user
    # idea on seeing that explained: "if we're normalizing anyway,
    # shouldn't this just BE a 3-way split control?" It should. A
    # two-handle slider's three segments (0->h1, h1->h2, h2->100) can't
    # help but sum to 100 — no normalising, no rounding-to-100 trick,
    # because there's nothing else they could sum to.
    #
    # Only used to SEED the slider's starting position from whatever was
    # last applied — prev_w_avg etc. are fractions of 1.0, which don't
    # divide evenly into whole percentages, hence the rounding helper.
    # The legend below reads the slider's own LIVE return value instead
    # (h1, h2 — already whole numbers, no rounding needed), which is
    # what makes it track the drag in real time rather than only
    # updating once Submit is clicked.
    pct_avg, pct_peak, pct_target = _round_pcts_to_100((prev_w_avg, prev_w_peak, prev_w_target))

    def _snap5(n: int) -> int:
        """Nearest multiple of 5, clamped to [0, 100] — matches the
        slider's own step=5, so a saved split like 34/33/33 (not a
        multiple of 5) still seeds a legal handle position."""
        return max(0, min(100, round(n / 5) * 5))

    seed_h1 = _snap5(pct_avg)
    seed_h2 = max(seed_h1, _snap5(pct_avg + pct_peak))

    # Full width now, not confined to a 3-of-4 column — a first version
    # shared a row with the submit button (matching the old 3-slider
    # layout), which left the slider narrower than the legend below it
    # ("make the composite upside weights scale longer so it reaches the
    # end of the % after analyst target" — the legend is full-width, the
    # slider wasn't, so it visibly stopped short). The whole block is
    # wrapped in one keyed container so the submit button (below) can be
    # pinned into it precisely, the same "position the wrapper, not the
    # widget" technique the Focus List cards' "+" button already uses —
    # see .vg-card-head / st-key-focuscard- for the original of this
    # pattern, and its own comment for why it has to be the wrapper.
    with st.container(key="weights-block"):
        # The widget's OWN label doubles as the section heading (styled
        # in theme.py to match) rather than a separate st.html() div
        # above it — a first version used label_visibility="collapsed"
        # plus a separate custom heading, which silently broke the help
        # tooltip: the tooltip icon sits inside the same label row
        # Streamlit collapses, so it was still in the DOM but rendered
        # at 0x0, unreachable. One real label avoids that trap entirely.
        h1, h2 = st.slider(
            "Weights used to compute Composite Upside%",
            min_value=0, max_value=100,
            value=(seed_h1, seed_h2),
            step=5,
            key="filt_weights_range",
            help=(
                "Two handles split the bar into three shares — how much "
                f"the {sma_window_input}-day moving average, the 52-week "
                "high, and the analyst target each count toward the "
                "blended Composite Upside % score. Drag either handle; "
                "the three shares always add up to 100%."
            ),
        )
        w_avg_raw, w_peak_raw, w_target_raw = h1, h2 - h1, 100 - h2

        # Streamlit's own slider fill is a CSS linear-gradient with hard
        # color stops at the handle positions (confirmed by inspecting
        # the live DOM) — overridden here with a 3-stop version instead
        # of 2, so the bar itself shows the three shares as three
        # colors, not just "filled between the handles." Scoped to this
        # widget's key so it doesn't touch any other slider. Now that
        # dragging reruns the script (no more st.form()), this redraws
        # on every drag tick, live.
        st.html(f"""
            <style>
            [class*="st-key-filt_weights_range"] [role="group"] > div:first-child > div:first-child {{
                background: linear-gradient(to right,
                    var(--vg-weight-1) 0%, var(--vg-weight-1) {h1}%,
                    var(--vg-weight-2) {h1}%, var(--vg-weight-2) {h2}%,
                    var(--vg-weight-3) {h2}%, var(--vg-weight-3) 100%
                ) !important;
            }}
            </style>
        """)

        # Reads h1/h2 directly (the slider's live return value), NOT
        # pct_avg/pct_peak/pct_target (which only reflect the last
        # APPLIED state) — this is the fix for "the shades and the %
        # below the scale did not follow [the drag], it changed only
        # when I clicked submit." h1, h2-h1, 100-h2 are already whole
        # numbers summing to 100 by construction, so no rounding call
        # is needed here the way seeding the slider above needed one.
        st.html(
            '<div class="vg-weights-legend">'
            f'<span><i style="background:var(--vg-weight-1);"></i>{sma_window_input}-day avg <b>{h1}%</b></span>'
            f'<span><i style="background:var(--vg-weight-2);"></i>52-week high <b>{h2 - h1}%</b></span>'
            f'<span><i style="background:var(--vg-weight-3);"></i>Analyst target <b>{100 - h2}%</b></span>'
            '</div>'
        )

        # An arrow rather than "Apply Filters". `help` is kept here
        # (unlike the cards' bare "+") because a lone arrow gives no
        # hint on its own that it COMMITS the settings — nothing in the
        # Opportunity Map/Focus List updates until it's pressed, even
        # though the weights legend/bar above now do update live. A
        # plain st.button, not st.form_submit_button — there's no
        # st.form() left to submit; see the container comment above for
        # why. Pinned into the weights block's right edge, vertically
        # centered against the label+slider+legend stack, via the same
        # absolute-positioned-wrapper technique as the card "+" button —
        # it used to sit in its own column next to just the sliders,
        # which read as "lying around" once the slider went full-width
        # and left it with no natural column to anchor to.
        submitted = st.button(
            "→", type="primary", help="Apply filters", key="weights_submit"
        )

if submitted:
    analytics.track_filters_applied()
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
    # "market" only appears when it's not the default — same "clean
    # until something changes" property the other filter params have.
    market_param = {} if market.id == DEFAULT_MARKET_ID else {"market": market.id}
    st.query_params.from_dict(
        {**market_param, **filters_to_query_params(st.session_state.applied_filters, market)}
    )
    # Without this, the Composite Upside weights readout above the
    # sliders (which reads applied_filters["weights"], same as
    # everything else below) would show the OLD weights for one extra
    # render — it's computed earlier in THIS script pass, before this
    # very update runs. Same fix already used for the market switch
    # above: restart the script now so the read that already happened
    # further up gets redone against the fresh value.
    st.rerun()

# Everything below reads ONLY from st.session_state.applied_filters —
# never from the form's raw widget variables above — so dragging a
# slider without clicking "Apply Filters" changes nothing on the page,
# even across an unrelated rerun (e.g. clicking a heatmap box).
af = st.session_state.applied_filters
cap_value_by_label = dict(market.cap_range_options)
cap_range = (cap_value_by_label[af["cap_range"][0]], cap_value_by_label[af["cap_range"][1]])
rating_threshold = af["rating_threshold"]
sma_window, weights, composite_cutoff = af["sma_window"], af["weights"], af["composite_cutoff"]
# Every LITERAL "$" escaped to "\$" — a PAIR of unescaped $ in Streamlit
# markdown gets read as LaTeX math mode, and "$10B" next to "$10T" is
# exactly that pair. Escaping wherever "$" actually occurs (rather than
# assuming every label starts with one) is what keeps this correct for
# ₹-denominated labels too: a rupee label has no "$" in it at all, so
# .replace() leaves it untouched instead of prepending a stray visible
# backslash the way an unconditional f"\\{label}" would have.
low_label, high_label = af["cap_range"]
cap_range_display = f"{low_label.replace('$', '\\$')}–{high_label.replace('$', '\\$')}"

if scan is not None:
    # Recompute EVERY scanned ticker's evaluation against the currently
    # APPLIED filters, once per page run. qualifying_results (rating +
    # cap range + composite cutoff all passed) drives BOTH the heatmap
    # and the Focus List, so they always show the same set. Computed
    # BEFORE the "Showing:" caption below (wants the
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

# One line under the filter panel, not two. The bold
# "**N tickers** currently match." sentence that used to sit here was
# removed: the same count was ALSO repeated under the Opportunity Map
# heading, and between the two of them plus a divider the gap between
# the filters and the map was mostly empty space. The count now appears
# once, on the map's own caption where it describes what you're looking
# at.
_caption_pct_avg, _caption_pct_peak, _caption_pct_target = _round_pcts_to_100(weights)
st.caption(
    f"Showing: {cap_range_display} market cap · "
    f"rating ≤ {rating_threshold:.1f} · {sma_window}-day avg weighted "
    f"{_caption_pct_avg}/{_caption_pct_peak}/{_caption_pct_target} · "
    f"Composite Upside ≥ {composite_cutoff}%"
)

st.divider()

if scan is None:
    st.info("No scan has run yet. Run `run_daily_scan.py` first to generate results.")
else:
    # --- One heatmap: Composite Upside %, the same metric that drives ----
    # the focus list below it (was 4 separate slices across
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
        # 3-across grid (back to the Option 3 mockup's card
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
                    render_focus_card(r, sma_window, weights, market)

# The bottom "See full methodology →" link was removed —
# the header link above covers it, and the emoji icon it carried was
# the last one left on the page.

# The full disclaimer text, moved here from a yellow st.warning slab
# that used to sit above the page title. It's the same
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
