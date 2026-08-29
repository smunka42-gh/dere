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
import math
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
    APP_VERSION,
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
    the moving average for `sma_window`, the current price ("Today"),
    the analyst median target, and the 52-week high.

    Built from absolutely-positioned <div>s rather than SVG, because
    st.html() strips <svg> elements entirely.

    Layout — three rules, in order:

    1. Each point keeps its own colour, and owns a dot on the track plus
       a vertical LEADER LINE in that same colour running out to its
       label. The label is centred on its leader, so a label is tied to
       its dot by position AND colour — never by proximity alone. The
       dot NEVER moves off its true value.

    2. Leaders alternate up/down by position, so two ADJACENT points can
       never share a side.

    3. Alternating still leaves points TWO apart on the same side (with
       five points, 1/3/5 go up and 2/4 go down). When those land close
       together — three or more values clustered in a narrow band, e.g.
       a stock trading just above its 52-week low — each successive
       crowded label on that side gets a LONGER leader, one step per
       point, so their label blocks stack at different heights and
       cannot touch. The step is derived from the tallest label block,
       so a bumped label always fully clears the one before it.

    The container's height is computed from how far the leaders actually
    reach, so an uncrowded scale stays compact and only a genuinely
    clustered one grows tall.

    The scale is NOT clamped to the 52-week high: an analyst target can
    legitimately sit above it, and clamping would hide exactly the
    signal Composite Upside % exists to catch.

    The moving average's price is not stored anywhere, only its upside
    percentage. It is reconstructed here as the exact inverse of
    compute_upside_pct(): ref = current * (1 + upside / 100).
    """
    current = r.get("most_recent_close")
    low = r.get("fifty_two_week_low")
    high = r.get("fifty_two_week_high")
    target = r.get("analyst_target_median")
    high_upside = r.get("upside_to_52w_high_pct")
    target_upside = r.get("upside_to_target_pct")
    up_from_low = (current - low) / low * 100 if None not in (current, low) and low else None

    # BOTH moving averages are plotted, not just the one the filter
    # panel currently selects — the scan stores every window's upside
    # (sma_upside_by_window), so showing both costs nothing and lets
    # the modal answer "where does this sit against its short AND long
    # trend" in one look, rather than only the trend that happens to be
    # filtered on. The filter's own choice still drives the ranking and
    # the card stats; this view is where the fuller picture belongs.
    sma_by_window = r.get("sma_upside_by_window") or {}

    def _sma_point(window: int) -> tuple[float | None, float | None]:
        """Price and upside for one moving-average window, or (None, None).

        Falls back to the pre-computed single-window figure when the
        per-window map is missing (older scan files) and that figure
        belongs to the window being asked for.
        """
        upside = sma_by_window.get(str(window))
        if upside is None and window == sma_window:
            upside = r.get("upside_to_recent_avg_pct")
        if upside is None or current is None:
            return None, None
        return current * (1 + upside / 100), upside

    sma50_price, sma50_upside = _sma_point(50)
    sma200_price, sma200_upside = _sma_point(200)

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

    # One distinct colour per point, so the scale reads as a set of
    # identifiable anchors rather than several interchangeable grey
    # ones (an earlier scheme reused one muted grey for both the moving
    # average and the analyst target, so neither could be traced to its
    # own label by colour).
    #
    # Low/high keep the app's semantic red/green — a 52-week low IS the
    # bad end and the high IS the good end, so borrowing those tokens
    # carries meaning rather than being decorative. Today takes the
    # accent blue, the app's existing "look at this" colour, matching
    # the price on the Focus List cards. Analyst target takes purple.
    #
    # The two moving averages deliberately share one warm hue at two
    # very different lightnesses: they are the same KIND of quantity
    # (the same measure over a short vs long window), so reading as a
    # pair is informative, while the lightness gap plus their own
    # labels keeps them separable. This is not the "three shades of one
    # blue" problem hit on the weights slider — there, every segment
    # was a shade of the same colour with nothing else to tell them
    # apart; here it is one pair among four other distinct hues.
    C_LOW = "var(--vg-negative)"
    C_SMA_50 = "#b8860b"
    C_SMA_200 = "#6b4423"
    C_TODAY = "var(--vg-accent)"
    C_TARGET = "#7d5ba6"
    C_HIGH = "var(--vg-positive)"

    # (label, value, pct, colour, is_hero)
    points = [
        ("52W Low", low, None, C_LOW, False),
        ("50D Avg", sma50_price, sma50_upside, C_SMA_50, False),
        ("200D Avg", sma200_price, sma200_upside, C_SMA_200, False),
        ("Today", current, up_from_low, C_TODAY, True),
        ("Analyst Target", target, target_upside, C_TARGET, False),
        ("52W High", high, high_upside, C_HIGH, False),
    ]
    valid = [p for p in points if p[1] is not None]
    if len(valid) < 2:
        return '<div style="font-size:12px; color:var(--vg-text-muted);">Not enough price data for the scale.</div>'

    values = [p[1] for p in valid]
    lo, hi = min(values), max(values)
    span = hi - lo if hi > lo else 1

    # Sorted left-to-right by POSITION, not by identity, so the up/down
    # alternation always separates the two closest points regardless of
    # which two they happen to be.
    ordered = sorted(valid, key=lambda p: p[1])

    # Label block width. Fixed and narrow so a long label WRAPS instead
    # of growing sideways into a neighbour — wrapping spends vertical
    # space (which the leader system already manages) instead of
    # horizontal space (which is exactly what runs out when points
    # cluster).
    LABEL_W = 88
    HALF_LABEL = LABEL_W // 2

    # Rough px-per-character for the uppercase 8.5px label line, used
    # only to predict whether a label will wrap so the block's height
    # can be estimated for stacking. Slightly generous, so an
    # unexpected wrap can never cause an overlap.
    LABEL_CHAR_PX = 5.6
    LINE_H_LABEL = 12
    LINE_H_PRICE = 16
    LINE_H_PCT = 13

    LEADER_BASE = 14
    LEADER_W = 2  # leader thickness; heavy enough to read as a real line

    # Two same-side labels closer than this (in % of track width) are
    # treated as at risk of touching. LABEL_W is a fixed px width, so
    # what it costs as a PERCENTAGE depends on how wide the scale
    # renders. This modal is desktop-first, where the scale measures
    # roughly 600-1300px depending on viewport, making an 88px label
    # ~7-15% of the track; 16 covers the narrow end of that range with
    # a little margin. Deliberately NOT set for phone widths (~287px,
    # where the same label is ~31%) — doing that over-triggers the
    # height tiers on desktop and makes the common, uncrowded case
    # taller than it needs to be.
    CLOSE_PCT = 16

    # --- Pass 1: position, side, crowding tier, and label height -----
    placed = []
    prev_on_side: dict[int, tuple[float, int] | None] = {0: None, 1: None}
    for i, (label, value, pct, colour, is_hero) in enumerate(ordered):
        pos = (value - lo) / span * 100
        side = i % 2  # 0 = label above the track, 1 = below

        # Tier climbs by one for each successive same-side point that
        # lands within CLOSE_PCT of the previous one, and resets as soon
        # as a point has room — so a run of 3+ clustered points stacks
        # at 3+ distinct heights, while an uncrowded scale stays flat.
        prev = prev_on_side[side]
        tier = prev[1] + 1 if prev is not None and abs(pos - prev[0]) < CLOSE_PCT else 0
        prev_on_side[side] = (pos, tier)

        lines = max(1, math.ceil(len(label) * LABEL_CHAR_PX / LABEL_W))
        label_h = lines * LINE_H_LABEL + LINE_H_PRICE + (LINE_H_PCT if pct is not None else 0)

        placed.append(
            {
                "label": label, "value": value, "pct": pct, "colour": colour,
                "is_hero": is_hero, "pos": pos, "side": side, "tier": tier,
                "label_h": label_h, "dot": 13 if is_hero else 9,
            }
        )

    # One step must clear the tallest label block outright, or a bumped
    # label would still land on top of the one it was bumped past.
    LEADER_STEP = max(p["label_h"] for p in placed) + 8

    # --- Pass 2: how far each side actually reaches ------------------
    # The container is sized to what the layout genuinely needs, so an
    # uncrowded scale doesn't reserve room for tiers it never uses.
    def _reach(side: int) -> float:
        on_side = [p for p in placed if p["side"] == side]
        if not on_side:
            return 40.0
        return max(
            p["dot"] / 2 + LEADER_BASE + p["tier"] * LEADER_STEP + p["label_h"] + 10
            for p in on_side
        )

    reach_up, reach_down = _reach(0), _reach(1)
    total_h = reach_up + reach_down
    axis = reach_up  # px from the container's top down to the track

    # The track is INSET from the container's edges by half a label
    # width, so a point sitting at either extreme of the value range
    # still has room to centre its label on its own dot. Previously the
    # track spanned the full width and the label was clamp()ed inward
    # to avoid clipping, which pulled it off-centre from its leader
    # exactly where values hit the extremes — reported on HDFCLIFE.NS,
    # where "52W Low" sat visibly to the right of its own red leader.
    # Reserving the room up front removes the need to clamp at all, so
    # dot, leader and label always share one x.
    def _x(pos: float) -> str:
        return f"calc({HALF_LABEL}px + (100% - {2 * HALF_LABEL}px) * {pos / 100:.4f})"

    parts = [
        f'<div style="position:absolute; left:{HALF_LABEL}px; right:{HALF_LABEL}px; '
        f'top:{axis - 1.5:.1f}px; height:3px; '
        f'background:var(--vg-border); border-radius:2px;"></div>'
    ]

    for p in placed:
        x = _x(p["pos"])
        half_dot = p["dot"] / 2
        leader = LEADER_BASE + p["tier"] * LEADER_STEP

        # The leader runs all the way to the track's centre line rather
        # than stopping at the dot's outer edge, and the dot is painted
        # over it (higher z-index). That guarantees the line meets the
        # dot with no seam, instead of leaving the hairline gap a
        # fixed stand-off produced.
        span = half_dot + leader
        if p["side"] == 0:
            leader_top = axis - span
            label_style = f"bottom:{total_h - leader_top + 2:.1f}px;"
        else:
            leader_top = axis
            label_style = f"top:{leader_top + span + 2:.1f}px;"

        # Leader line, in the point's own colour.
        parts.append(
            f'<div style="position:absolute; left:{x}; top:{leader_top:.1f}px; '
            f"height:{span:.1f}px; width:{LEADER_W}px; transform:translateX(-50%); "
            f"background:{p['colour']}; opacity:0.85; z-index:1;\"></div>"
        )

        # Dot, painted over the leader's end.
        parts.append(
            f'<div style="position:absolute; left:{x}; top:{axis:.1f}px; '
            f"transform:translate(-50%,-50%); width:{p['dot']}px; height:{p['dot']}px; "
            f"border-radius:50%; background:{p['colour']}; border:2px solid var(--vg-bg); "
            f'box-shadow:0 0 0 1px var(--vg-border); z-index:3;"></div>'
        )

        pct_html = ""
        if p["pct"] is not None:
            pct_colour = "var(--vg-positive)" if p["pct"] >= 0 else "var(--vg-negative)"
            shown = f"{p['pct']:+.0f}%" if abs(p["pct"]) >= 100 else f"{p['pct']:+.1f}%"
            pct_html = (
                f'<div style="color:{pct_colour}; font-weight:700; font-size:10px; '
                f'font-variant-numeric:tabular-nums; line-height:1.3;">{shown}</div>'
            )

        # Label block, centred on the same x as its dot and leader.
        parts.append(
            f'<div style="position:absolute; {label_style} left:{x}; '
            f"transform:translateX(-50%); width:{LABEL_W}px; text-align:center; "
            f'z-index:2;">'
            f'<div style="color:{p["colour"]}; font-size:8.5px; font-weight:700; '
            f'text-transform:uppercase; letter-spacing:0.05em; line-height:1.35;">{p["label"]}</div>'
            f'<div style="color:{p["colour"]}; font-weight:{800 if p["is_hero"] else 700}; '
            f'font-size:{12.5 if p["is_hero"] else 11.5}px; font-variant-numeric:tabular-nums; '
            f'line-height:1.25;">{_price(p["value"])}</div>'
            f"{pct_html}</div>"
        )

    return (
        f'<div style="position:relative; height:{total_h:.0f}px; margin:0 4px;">'
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

    # Company name and market cap moved OFF the card face and into the
    # ticker's hover tooltip. Both were costing a full row each while
    # being the least-scanned things on the card — and long names
    # ("Oil and Natural Gas Corp.") wrapped to two lines, leaving the
    # grid's cards at uneven heights. Nothing is lost: the detail modal
    # still shows both in full, and the tooltip keeps them one hover
    # away here.
    card_tooltip = clean_company_name(full_company_name)
    market_cap_text = market.format_market_cap(r.get("market_cap"))
    if market_cap_text:
        card_tooltip = f"{card_tooltip} · {market_cap_text}"

    with st.container(border=True, key=f"focuscard-{r['ticker']}"):
        st.html(
            f'<div class="vg-card-head">'
            f"<div>"
            f'<div class="vg-card-ticker" title="{card_tooltip}">{r["ticker"]}</div>'
            f"</div>{pill}</div>"
            f'<div class="vg-card-tagrow">'
            f'<span class="vg-cap-tag" style="background:{tier_color};">'
            f'{cap_tier or "Cap n/a"}</span>'
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
        f"{len(all_results)} tickers · v{APP_VERSION}"
    )
else:
    scan_meta = f"No scan data yet · v{APP_VERSION}"

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
        # The ticker lookup lists only the CURRENT market's symbols, so a
        # leftover selection ("ORCL" while now on Nifty 50) would not
        # exist in the new options list — same class of stale-value crash
        # the filter widgets above are cleared to avoid.
        "ticker_lookup", "ticker_lookup_opened",
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

# --- Look up any ticker, filters or no filters -----------------------
# Deliberately drawn from EVERY scanned ticker, not from
# qualifying_results — the Focus List can only ever open something that
# already cleared the filters, so a lookup restricted to the same set
# would add nothing. Being able to pull up a name the filters rejected
# (or one you hold and just want to check) is the whole point.
#
# A selectbox rather than a free-text box: Streamlit's selectbox already
# filters as you type, so it behaves like the requested "type a ticker"
# field while making a typo or an unlisted symbol impossible.
if scan is not None and live_results:
    by_ticker = {r["ticker"]: r for r in live_results}
    lookup_col, _spacer = st.columns([1, 3])
    with lookup_col, st.container(key="ticker-lookup"):
        picked_ticker = st.selectbox(
            "Look up a ticker",
            options=["", *sorted(by_ticker)],
            format_func=lambda t: "Type to search…" if t == "" else t,
            key="ticker_lookup",
            help=(
                "Opens the same price scale as the + on a Focus List card, "
                "for any ticker in this market — including ones the filters "
                "above are currently excluding."
            ),
        )

    # Open on CHANGE, not on every rerun: the selectbox keeps its value
    # after the dialog is dismissed, so re-opening whenever it is simply
    # non-empty would make the modal impossible to close.
    if picked_ticker and picked_ticker != st.session_state.get("ticker_lookup_opened"):
        st.session_state["ticker_lookup_opened"] = picked_ticker
        show_detail_dialog(by_ticker[picked_ticker], sma_window, weights, market)
    elif not picked_ticker:
        # Back to the placeholder — forget what was shown, so picking the
        # same ticker again re-opens it rather than silently doing nothing.
        st.session_state.pop("ticker_lookup_opened", None)

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
