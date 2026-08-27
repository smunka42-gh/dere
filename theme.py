"""
Vantage — visual theme.

Streamlit's default look (the gray sidebar-less "school project" feel
) comes from its own built-in CSS. Streamlit doesn't
expose a way to fully replace that from Python — the supported trick
is to inject our OWN <style> block via st.html(), targeting Streamlit's
internal `data-testid` attributes (the most stable hooks Streamlit
gives us — plain class names change between versions, data-testid
values change far less often).

## How this CSS is injected — two bugs, and why it looks like this now

This went through st.markdown → st.html → back to st.markdown, and the
history matters because both ends of that look wrong out of context:

1. FIRST attempt used st.markdown(unsafe_allow_html=True) and the page
   showed broken fragments of raw CSS as visible text. Diagnosed at the
   time as Markdown mangling CSS attribute selectors, and "fixed" by
   switching to st.html().
2. That diagnosis was WRONG, and the switch silently broke the theme
   COMPLETELY for a while — st.html() sanitizes away `<style>` and
   `<link>` elements entirely (the same sanitizer that strips `<svg>`,
   found earlier when the price scale had to be rebuilt out of divs).
   Detectable by checking the live DOM: `--vg-positive` and
   every other token resolved to the empty string, no style tag on the
   page contained "Manrope", and document.body's font was still
   Streamlit's default "Source Sans". Everything that still looked
   styled was coming from .streamlit/config.toml, not from this file.
3. The REAL cause of bug 1 was indentation, not selectors. In
   CommonMark, a `<style>` tag starting at column 0 opens a raw HTML
   block whose contents are passed through verbatim — but indent that
   opening tag by 4+ spaces and it becomes an indented CODE block
   instead, which is exactly "CSS rendered as visible text." The CSS
   here sits inside an indented Python string, so it MUST be dedented
   before being handed to st.markdown.

Hence: st.markdown(textwrap.dedent(...), unsafe_allow_html=True), with
the webfont pulled in by an @import INSIDE the style block rather than
a `<link>` tag (st.markdown strips `<link>` too). If this file's styles
ever appear to do nothing again, check `--vg-accent` in the browser
console FIRST — an empty value means the whole block is being dropped
again, not that an individual selector stopped matching.

Worth being clear about: this reskins Streamlit's native
widgets (tabs, buttons, expanders, metrics) — it does NOT rebuild them
as custom HTML. That means we get real interactivity (click-to-select
on the heatmaps, working buttons, working expanders) for free, but we
are working within Streamlit's actual component structure, not
designing totally free-form. If a future Streamlit upgrade changes its
internal DOM, some of these selectors could stop matching — low risk,
but worth knowing about.

This file picked the "Minimal Data-First" visual direction review
chose from the three mockups: clean white background,
Manrope typeface, restrained blue accent, rounded cards. One
deliberate refinement on top of the original mockup: the blue accent
is reserved ONLY for "this is a curated pick" badges — actual upside
numbers (Composite Upside %, Delta 1/2) stay in the existing green/red
scale. Two different visual meanings (a badge vs. a data value)
shouldn't share one color, or the color stops meaning anything
specific.

## Credits

Manrope typeface via Google Fonts (Open Font License, no attribution
required beyond normal usage). Visual language inspired by the general
"modern SaaS dashboard" style common to products like Stripe, Linear,
and Robinhood (rounded cards, restrained accent color, generous
whitespace) — a widely-used design pattern, not copied from any one
product's actual code or assets.
"""

import textwrap

import streamlit as st

# Placeholder product name — review hadn't locked in a final name as of
# this redesign (floated "Daily Market Opportunity Landscape" and a few
# others). Kept as ONE constant here, used everywhere the brand name
# appears, so renaming later is a one-line change instead of a find/
# replace across every file.
APP_NAME = "Vantage"

# Color tokens for the theme. Named by MEANING, not by literal color,
# so if a shade ever changes, every place that uses it for that reason
# updates together instead of needing a hunt-and-replace.
_BG = "#ffffff"
_BG_ALT = "#fafbfc"          # subtle panel background (expanders, code blocks)
_TEXT = "#16181d"
_TEXT_MUTED = "#6b7280"
_BORDER = "#eceef1"
_ACCENT = "#3b6e91"          # reserved for "this is a curated pick" signals — badges, active tab, links, primary buttons — never for a raw upside number
_ACCENT_SOFT = "#eef2f6"
_POSITIVE = "#1f7d4c"        # reserved for positive upside numbers only
_POSITIVE_SOFT = "#e7f6ee"
_NEGATIVE = "#d1544b"        # reserved for negative upside numbers only
_NEGATIVE_SOFT = "#fbe4e2"
_RADIUS = "12px"

# Public re-exports — app.py needs these directly (e.g. the heatmap's
# custom legend, market-cap-tier coloring on Focus List cards) without
# reaching into this module's "private" (leading-underscore) tokens.
POSITIVE_COLOR = _POSITIVE
NEGATIVE_COLOR = _NEGATIVE

# Market-cap-tier colors — deliberately a SEPARATE palette from the
# accent/positive/negative tokens above, so a tier tag never gets
# confused with a "curated pick" badge or an upside number. the
# priority order: mostly invests in large caps, wants
# visibility into mid/small caps without them competing for attention —
# large cap gets the strongest/darkest color, small cap the lightest.
CAP_TIER_COLORS = {
    "Large Cap": "#2c3e50",
    "Mid Cap": "#b8860b",
    "Small Cap": "#9aa1ab",
}


def inject_theme_css() -> None:
    """
    Injects the Vantage theme's CSS into the current page. Call this
    once, immediately after st.set_page_config() — it must run before
    any other Streamlit widget so the styles are present when the rest
    of the page renders. Needs to be called on EVERY page file
    (app.py, and each file under pages/) since Streamlit runs each
    page as its own independent script — CSS injected on one page does
    not carry over to another.
    """
    st.markdown(
        textwrap.dedent(
            f"""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&display=swap');
        :root {{
            --vg-bg: {_BG};
            --vg-bg-alt: {_BG_ALT};
            --vg-text: {_TEXT};
            --vg-text-muted: {_TEXT_MUTED};
            --vg-border: {_BORDER};
            --vg-accent: {_ACCENT};
            --vg-accent-soft: {_ACCENT_SOFT};
            --vg-positive: {_POSITIVE};
            --vg-positive-soft: {_POSITIVE_SOFT};
            --vg-negative: {_NEGATIVE};
            --vg-negative-soft: {_NEGATIVE_SOFT};
            --vg-radius: {_RADIUS};
        }}

        /* Base typography + page background. html/body covers text that
           renders outside Streamlit's own component wrappers. */
        html, body, [class*="css"] {{
            font-family: 'Manrope', system-ui, sans-serif;
        }}
        [data-testid="stAppViewContainer"], [data-testid="stHeader"] {{
            background: var(--vg-bg);
        }}
        /* Streamlit's header is 60px tall, OPAQUE WHITE and sits at
           z-index 999990 — so it paints OVER the top of the page's own
           content. With padding-top at 40px the nav meta started at
           content, clipping the top of whatever sits under it.

           With toolbarMode "minimal" and the sidebar nav hidden, that
           header renders empty — nothing to show and no reason to
           reserve space — so it is collapsed to zero height. This both
           prevents the clipping and reclaims 60px on every page. */
        [data-testid="stHeader"] {{
            height: 0 !important;
            min-height: 0 !important;
        }}
        [data-testid="stMainBlockContainer"] {{
            padding-top: 1.75rem;
            max-width: 1100px;
        }}
        body, [data-testid="stAppViewContainer"] {{
            color: var(--vg-text);
        }}

        /* Headings — bold, tight letter-spacing, matches the "Minimal
           Data-First" mockup's confident type scale. Explicit
           font-family here too: Streamlit ships its own "Source Sans"
           rule scoped directly to h1/h2/h3, which outranks the broader
           html/body rule above — without repeating it here, headings
           silently stayed on Streamlit's default font. */
        h1, h2, h3 {{
            font-family: 'Manrope', system-ui, sans-serif !important;
            font-weight: 800 !important;
            letter-spacing: -0.01em;
            color: var(--vg-text) !important;
        }}

        /* Same trap as the headings above, and it caught EVERY piece of
           markdown text on the site (checked with
           getComputedStyle: st.markdown paragraphs and st.caption were
           still rendering in Streamlit's "Source Sans" while the
           widgets, buttons and custom cards around them were in
           Manrope). Streamlit scopes its font rule directly to these
           containers, so the html/body rule never applied.

           This is why the whole Methodology page, the "N tickers
           currently match" lines, and every caption looked subtly off
           against the rest of the page.

           Two deliberate exclusions:
           - [data-testid="stIconMaterial"] renders its glyphs as FONT
             LIGATURES from the Material Symbols family. Forcing Manrope
             onto it doesn't restyle the icon, it prints the raw
             ligature name as text ("keyboard_arrow_right").
           - code/pre/kbd/samp stay monospace, which is the point of
             them. */
        [data-testid="stMarkdownContainer"],
        [data-testid="stMarkdownContainer"] *:not([data-testid="stIconMaterial"]):not(code):not(pre):not(kbd):not(samp),
        [data-testid="stCaptionContainer"],
        [data-testid="stCaptionContainer"] p,
        [data-testid="stCaptionContainer"] *:not([data-testid="stIconMaterial"]):not(code):not(pre),
        [data-testid="stWidgetLabel"],
        [data-testid="stWidgetLabel"] *:not([data-testid="stIconMaterial"]),
        [data-testid="stMetricValue"],
        [data-testid="stMetricLabel"],
        [data-testid="stMetricLabel"] *,
        .stButton button, .stButton button p,
        [data-testid="stLinkButton"] a, [data-testid="stLinkButton"] a p,
        [data-testid="stTab"], [data-testid="stTab"] * {{
            font-family: 'Manrope', system-ui, sans-serif !important;
        }}
        /* Restated after the sweep above so the monospace intent wins
           regardless of source order. */
        code, pre, kbd, samp,
        [data-testid="stMarkdownContainer"] code {{
            font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace !important;
        }}

        /* Captions and muted helper text throughout the app. 12px to
           match the nav meta line (the "Showing:"
           and "N tickers" lines were 14px and read too large — "more in
           line with the daily equity recommendations text at the top").
           The dialog scopes its own smaller size separately. */
        [data-testid="stCaptionContainer"], .stCaption {{
            font-size: 12px !important;
            color: var(--vg-text-muted) !important;
        }}

        /* Tabs — active tab gets the accent color + underline instead
           of Streamlit's default red. Streamlit 1.62 renders tabs with
           React Aria components, not the older BaseWeb structure most
           Streamlit CSS snippets online assume — [data-testid="stTab"]
           for each tab and .react-aria-SelectionIndicator for the
           active-tab underline are THIS version's real hooks (checked
           against the live page's actual DOM, not guessed). */
        [data-testid="stTab"] {{
            font-weight: 600;
            color: var(--vg-text-muted);
        }}
        [data-testid="stTab"][aria-selected="true"] {{
            color: var(--vg-accent) !important;
        }}
        [data-testid="stTab"] .react-aria-SelectionIndicator {{
            background-color: var(--vg-accent) !important;
        }}

        /* Expander (each recommendation row) — rounded card instead of
           Streamlit's plain bordered box. */
        [data-testid="stExpander"] {{
            border: 1px solid var(--vg-border) !important;
            border-radius: var(--vg-radius) !important;
            background: var(--vg-bg) !important;
            box-shadow: 0 1px 2px rgba(16,24,40,0.04);
        }}

        /* st.metric — bigger, bolder value, tabular numerals so digits
           line up column to column like a real financial table. */
        [data-testid="stMetricValue"] {{
            font-weight: 800;
            font-variant-numeric: tabular-nums;
            color: var(--vg-text);
        }}
        [data-testid="stMetricLabel"] {{
            color: var(--vg-text-muted);
            font-weight: 600;
        }}

        /* Buttons (Analyze, Yahoo/Google Finance links) — accent-blue
           filled primary, rounded to match the card language. */
        .stButton button, [data-testid="stLinkButton"] a {{
            border-radius: 8px !important;
            font-weight: 600 !important;
        }}
        .stButton button[kind="primary"], .stButton button {{
            background: var(--vg-accent) !important;
            color: #ffffff !important;
            border: none !important;
        }}
        [data-testid="stLinkButton"] a {{
            border: 1px solid var(--vg-border) !important;
            color: var(--vg-text) !important;
            background: var(--vg-bg) !important;
        }}
        [data-testid="stLinkButton"] a:hover {{
            border-color: var(--vg-accent) !important;
            color: var(--vg-accent) !important;
        }}

        /* Filter form — compacted well below Streamlit's defaults, which
           are sized for a full-page form rather than a dense control
           strip. Every value here was measured against the live DOM
           rather than guessed. The defaults being overridden: 15px
           padding, a 16px flexbox gap between stacked widgets, 14px
           widget labels, and 40px submit buttons with 16px text. Also
           the form's overall width (it was stretching to the full
           "wide" layout width, exaggerating every control's length),
           capping each slider's own width so it doesn't span its whole
           (still-wide) column, and shrinking buttons further. */
        [data-testid="stForm"] {{
            padding: 10px 14px 8px 14px !important;
            border: 1px solid var(--vg-border) !important;
            border-radius: var(--vg-radius) !important;
            max-width: 900px;
        }}
        /* 4px, not 0 — at 0 the "Filters" heading overlapped the first
           widget label by 16px (measured). */
        [data-testid="stForm"] [data-testid="stVerticalBlock"] {{
            gap: 4px !important;
        }}
        /* Each slider row measured 68px: a 24px label box wrapping 10.5px
           text, plus a 40px track block. Both carry padding sized for
           Streamlit's default type scale, which is much larger than this
           panel now uses — so the row was mostly empty space. */
        [data-testid="stForm"] [data-testid="stWidgetLabel"] {{
            min-height: 0 !important;
            margin-bottom: 0 !important;
        }}
        [data-testid="stForm"] [data-testid="stWidgetLabel"] p {{
            line-height: 1.3 !important;
        }}
        /* Panel sub-heading inside the form, styled to match the h3
           above it. */
        .vg-panel-label {{
            font-size: 11px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            color: var(--vg-text-muted);
            padding: 0;
            line-height: 1.3;
        }}

        [data-testid="stForm"] [data-testid="stWidgetLabel"] p {{
            font-size: 10.5px !important;
            font-weight: 600 !important;
            white-space: nowrap;
        }}
        /* Slider name and its value readout overlapped vertically by 4px.
           That only LOOKS cramped when the value also sits horizontally
           under the name — and the readout is positioned above the THUMB,
           so its offset moves with the value. Row 1 has the longest names
           AND left-positioned thumbs ("Moving-avg (days)" measured the
           value at offset 0, directly beneath a 93px name), while row 2's
           short names let the number clear them — which is exactly why
           the top row read as tighter than the bottom despite every
           measured gap being identical.

           Pushing the value+track block down turns the 4px overlap into
           a 4px gap, so name and value never collide at ANY value. The
           inner block is the only child of stSlider without a testid. */
        [data-testid="stForm"] [data-testid="stSlider"] > div:not([data-testid]) {{
            margin-top: 8px !important;
        }}

        /* The help "?" on the rating slider is a 16px icon next to 14px
           text, so that ONE label row was 2px taller than its neighbours
           — which pushed its slider down and made the label-to-track gap
           visibly different from the others ("space
           between 2.00 and max aggregate rating is too less and
           different than... 52 week high"). Matching the icon to the
           text height makes every label row identical. */
        [data-testid="stForm"] [data-testid="stTooltipIcon"],
        [data-testid="stForm"] [data-testid="stTooltipHoverTarget"] {{
            height: 14px !important;
            line-height: 14px !important;
        }}
        [data-testid="stForm"] [data-testid="stTooltipIcon"] svg {{
            width: 13px !important;
            height: 13px !important;
        }}
        /* Streamlit reserves a fixed row above every slider for the
           current-value readout and the min/max ticks. At this size the
           ticks are noise — the readout above the thumb already says the
           value — so they're hidden and the reserved space reclaimed.
           This is the single biggest saving in the panel. */
        [data-testid="stForm"] [data-testid="stSliderTickBar"] {{
            display: none !important;
        }}
        [data-testid="stForm"] [data-testid="stSliderThumbValue"] {{
            font-size: 11px !important;
        }}
        [data-testid="stForm"] [data-testid="stElementContainer"] {{
            margin-bottom: 0 !important;
        }}
        [data-testid="stForm"] [data-testid="stSlider"] {{
            max-width: 200px;
        }}
        /* Square arrow button — sized like the cards' "+" chip so the
           panel's one action reads as the same family of control. */
        [data-testid="stFormSubmitButton"] button {{
            width: 32px !important;
            height: 32px !important;
            min-height: 0 !important;
            padding: 0 !important;
            border-radius: 8px !important;
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
        }}
        [data-testid="stFormSubmitButton"] button p {{
            font-size: 16px !important;
            font-weight: 700 !important;
            line-height: 1 !important;
            margin: 0 !important;
        }}
        /* Left-aligned in its slot ("apply filter arrow
           button placement not good"). It now occupies the 4th slider
           slot of row 2, so starting at that slot's left edge puts it on
           the same vertical line the sliders above it start on, instead
           of floating at the far edge of the panel. */
        [data-testid="stForm"] [data-testid="stFormSubmitButton"] {{
            display: flex !important;
            justify-content: flex-start !important;
            width: 100% !important;
        }}
        [data-testid="stMultiSelectTagsContainer"] span[data-tag] {{
            font-size: 11px !important;
        }}

        /* Alert boxes (disclaimer warning, info/success banners) —
           softened corners, kept Streamlit's own color coding (yellow/
           blue/green) since that's a real severity signal, not just
           decoration. */
        [data-testid="stAlert"] {{
            border-radius: var(--vg-radius) !important;
        }}

        /* Dividers — lighter than Streamlit's default. */
        hr {{
            border-color: var(--vg-border) !important;
        }}

        /* Custom "curated pick" badge — used in render_detail_card
           instead of a plain emoji, in the reserved accent blue so it
           never visually collides with the green/red upside numbers
           sitting right next to it. */
        .vg-badge {{
            display: inline-block;
            font-size: 11.5px;
            font-weight: 700;
            letter-spacing: 0.03em;
            text-transform: uppercase;
            padding: 4px 10px;
            border-radius: 20px;
            background: var(--vg-accent-soft);
            color: var(--vg-accent);
            margin-bottom: 6px;
        }}
        .vg-badge-muted {{
            background: var(--vg-bg-alt);
            color: var(--vg-text-muted);
        }}

        /* Upside-number pill — used on Focus List cards for the
           Composite Upside % itself. Deliberately green/red (NOT the
           accent blue) — this pill IS a data value, not a "this is a
           curated pick" signal, so it follows the same color rule as
           every other upside number in the app. */
        .vg-pill-positive, .vg-pill-negative {{
            display: inline-block;
            font-size: 12px;
            font-weight: 700;
            padding: 4px 10px;
            border-radius: 20px;
            font-variant-numeric: tabular-nums;
        }}
        .vg-pill-positive {{
            background: var(--vg-positive-soft);
            color: var(--vg-positive);
        }}
        .vg-pill-negative {{
            background: var(--vg-negative-soft);
            color: var(--vg-negative);
        }}

        /* ---- Focus List row cards ----------------------------------
           The hook is the `st-key-focusrow-<ticker>` class that
           st.container(key=...) stamps on the container's own DOM node.

           This REPLACED a [data-testid="stVerticalBlockBorderWrapper"]
           rule that matched literally 0 elements on the live page —
           Streamlit stopped emitting that wrapper and now paints the
           border on the stVerticalBlock itself, so the old rule had
           been silently dead. Same lesson as the tabs selectors above:
           check the real DOM, don't trust a selector to keep working
           across Streamlit versions. The st-key-* class is the stable
           choice here precisely because it comes from OUR key, not from
           Streamlit's per-build st-emotion-cache-* hashes.

           Streamlit's own defaults for this container are 15px padding
           and a 16px flex gap between children — with 3 children that
           gap alone was ~32px of dead vertical space per row, which is
           most of what made the list feel bulky. */
        [class*="st-key-focusrow-"] {{
            border-radius: var(--vg-radius) !important;
            border-color: var(--vg-border) !important;
            box-shadow: 0 1px 2px rgba(16,24,40,0.04);
            padding: 10px 14px 8px 14px !important;
            gap: 2px !important;
            transition: border-color 120ms ease, box-shadow 120ms ease;
        }}
        [class*="st-key-focusrow-"]:hover {{
            border-color: #cbd5e1 !important;
            box-shadow: 0 2px 8px rgba(16,24,40,0.07);
        }}

        /* The "+" disclosure. Streamlit renders an expander as a
           full-width bordered bar, which read as a second card stacked
           inside each row. Stripped back to a small pill chip on the
           right: the expander still spans the full row when OPEN (so
           the detail card gets real width), it just stops LOOKING like
           a bar when closed. */
        [class*="st-key-focusrow-"] [data-testid="stExpander"],
        [class*="st-key-focusrow-"] [data-testid="stExpander"] details {{
            border: none !important;
            box-shadow: none !important;
            background: transparent !important;
        }}
        [class*="st-key-focusrow-"] [data-testid="stExpander"] summary {{
            width: fit-content !important;
            margin-left: auto !important;  /* right-aligns the chip */
            min-height: 0 !important;
            padding: 2px 10px !important;
            border: 1px solid var(--vg-border) !important;
            border-radius: 999px !important;
            background: var(--vg-bg) !important;
            transition: border-color 120ms ease, background 120ms ease;
        }}
        [class*="st-key-focusrow-"] [data-testid="stExpander"] summary:hover {{
            border-color: var(--vg-accent) !important;
            background: var(--vg-accent-soft) !important;
        }}
        /* Streamlit's own chevron icon — hidden so the chip shows one
           affordance (our "+"), not two competing ones. */
        [class*="st-key-focusrow-"] [data-testid="stExpander"] summary [data-testid="stIconMaterial"] {{
            display: none !important;
        }}
        [class*="st-key-focusrow-"] [data-testid="stExpander"] summary p {{
            font-size: 10px !important;
            font-weight: 700 !important;
            text-transform: uppercase;
            letter-spacing: 0.06em;
            color: var(--vg-text-muted) !important;
        }}
        [class*="st-key-focusrow-"] [data-testid="stExpander"] summary p::before {{
            content: "+";
            font-weight: 800;
            margin-right: 5px;
        }}
        [class*="st-key-focusrow-"] [data-testid="stExpander"] details[open] summary p::before {{
            content: "\\2212";  /* proper minus sign, not a hyphen */
        }}
        [class*="st-key-focusrow-"] [data-testid="stExpander"] summary:hover p {{
            color: var(--vg-accent) !important;
        }}

        /* ---- Opportunity Map (CSS-grid heatmap) --------------------
           Replaced a Plotly treemap so the tiles could match
           the Option 3 mockup exactly: 6px radius, 3px gaps, ticker +
           company at the top, big % anchored bottom-left. Plotly could
           do none of those, and forced a root strip across the top. */
        .vg-heatmap {{
            display: grid;
            grid-template-columns: repeat(12, 1fr);
            grid-auto-rows: 34px;
            grid-auto-flow: dense;
            gap: 3px;
        }}
        .vg-tile {{
            border-radius: 6px;
            padding: 10px 12px;
            position: relative;
            overflow: hidden;
            color: #fff;
        }}
        .vg-tile-tkr {{ font-weight: 800; line-height: 1.15; }}
        .vg-tile-co {{
            font-size: 11px;
            line-height: 1.3;
            margin-top: 2px;
            opacity: 0.85;
        }}
        .vg-tile-pct {{
            position: absolute;
            left: 12px;
            bottom: 10px;
            font-weight: 700;
            font-variant-numeric: tabular-nums;
        }}
        .vg-legend {{
            display: flex;
            align-items: center;
            gap: 10px;
            margin-top: 18px;
        }}
        .vg-legend-label {{
            font-size: 11px;
            color: var(--vg-text-muted);
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }}
        .vg-legend-bar {{
            width: 180px;
            height: 6px;
            border-radius: 3px;
            background: linear-gradient(90deg, var(--vg-negative), #c3cad1, var(--vg-positive));
        }}
        .vg-legend-nums {{
            font-size: 11px;
            color: var(--vg-text-muted);
            font-variant-numeric: tabular-nums;
        }}

        /* ---- Focus List tiles (3-across grid) ----------------------
           Modelled on the Option 3 mockup's "Top Picks Today" cards:
           ticker + company top-left, upside pill top-right, a large
           price, then a 3-column footer of the upside components. */
        [class*="st-key-focuscard-"] {{
            /* position:relative makes the card the anchor for the "+"
               button pinned into its corner further down. */
            position: relative;
            border-radius: var(--vg-radius) !important;
            border-color: var(--vg-border) !important;
            box-shadow: 0 1px 2px rgba(16,24,40,0.04);
            padding: 16px 16px 14px 16px !important;
            gap: 0 !important;
            height: 100%;
            transition: border-color 120ms ease, box-shadow 120ms ease;
        }}
        [class*="st-key-focuscard-"]:hover {{
            border-color: #cbd5e1 !important;
            box-shadow: 0 2px 8px rgba(16,24,40,0.07);
        }}
        .vg-card-head {{
            display: flex;
            align-items: flex-start;
            justify-content: space-between;
            gap: 8px;
            /* Clears the absolutely-positioned "+" button in the corner,
               so the upside pill sits to its left instead of under it. */
            padding-right: 32px;
        }}
        /* Type scale below is lifted verbatim from the Option 3 mockup's
           card ("the font of the cards in focus
           list... is different in option 3 and different here").
           The typeface was never the problem — Manrope loads and
           renders correctly, confirmed by measuring text width against
           the fallback stack. What differed was the TREATMENT: these
           had picked up negative letter-spacing (0.015em on the price,
           -0.01em on the ticker), which condenses the glyphs and reads
           as a different, tighter typeface. The mockup applies no
           tracking to either. Sizes/weights matched to it as well. */
        .vg-card-ticker {{
            font-size: 18px;
            font-weight: 800;
            line-height: 1.2;
        }}
        .vg-card-company {{
            font-size: 12px;
            color: var(--vg-text-muted);
            line-height: 1.35;
            margin-top: 1px;
        }}
        .vg-pill {{
            font-size: 11.5px;
            font-weight: 700;
            padding: 3px 9px;
            border-radius: 20px;
            white-space: nowrap;
            font-variant-numeric: tabular-nums;
            background: var(--vg-accent-soft);
            color: var(--vg-text-muted);
        }}
        .vg-pill-pos {{ background: var(--vg-positive-soft); color: var(--vg-positive); }}
        .vg-pill-neg {{ background: var(--vg-negative-soft); color: var(--vg-negative); }}
        .vg-card-tagrow {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-top: 8px;
        }}
        .vg-card-links {{ display: inline-flex; gap: 5px; }}
        /* Smaller variant of the .vg-ext chip for the cards, where it
           shares a row with the cap tag rather than a modal header. */
        .vg-ext-sm {{
            width: 21px !important;
            height: 21px !important;
            font-size: 9.5px !important;
        }}
        .vg-cap-tag {{
            font-size: 9px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.04em;
            padding: 2px 7px;
            border-radius: 10px;
            color: #fff;
        }}
        .vg-card-price {{
            font-size: 28px;
            font-weight: 800;
            font-variant-numeric: tabular-nums;
            margin-top: 14px;
            line-height: 1.15;
        }}
        /* 52-week range bar — sits between the price and the upside
           stats, showing where today's close falls between the 52w low
           and high. Occupies roughly the slot the mockup used for a
           price sparkline (which needs saved price history we don't
           have) and answers a question the sparkline couldn't: how much
           room is left to the high. */
        .vg-range {{ margin-top: 12px; }}
        .vg-range-track {{
            position: relative;
            height: 4px;
            border-radius: 2px;
            background: var(--vg-border);
        }}
        .vg-range-fill {{
            position: absolute;
            left: 0; top: 0; bottom: 0;
            border-radius: 2px;
            background: var(--vg-accent);
            opacity: 0.35;
        }}
        .vg-range-dot {{
            position: absolute;
            top: 50%;
            width: 9px; height: 9px;
            border-radius: 50%;
            background: var(--vg-accent);
            border: 2px solid var(--vg-bg);
            transform: translate(50%, -50%);
        }}
        .vg-range-cap {{
            display: flex;
            justify-content: space-between;
            align-items: baseline;
            margin-top: 7px;
            font-size: 10.5px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.03em;
            color: #9aa1ab;
        }}
        .vg-range-val {{
            color: var(--vg-text);
            font-variant-numeric: tabular-nums;
        }}

        .vg-card-stats {{
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 6px;
            margin-top: 12px;
            padding-top: 10px;
            border-top: 1px solid var(--vg-border);
        }}
        .vg-stat-label {{
            font-size: 10.5px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.03em;
            color: #9aa1ab;
            white-space: nowrap;
        }}
        .vg-stat-val {{
            font-size: 13.5px;
            font-weight: 600;
            font-variant-numeric: tabular-nums;
            margin-top: 3px;
        }}
        .vg-stat-val.vg-pos {{ color: var(--vg-positive); }}
        .vg-stat-val.vg-neg {{ color: var(--vg-negative); }}

        /* The tile's "+" button, pinned to the card's top-right corner
           beside the upside pill (was a chip at the bottom
           of the card; review found a corner "+" more intuitive, which
           matches the standard card-affordance convention).

           Streamlit renders a button as a block element and there's no
           way to nest one inside the st.html header markup, so instead
           the card becomes a positioning context and the button is
           absolutely placed into its corner. It remains a real
           st.button — only its position is CSS. .vg-card-head carries
           matching padding-right so the pill shifts left rather than
           sliding underneath it. */
        /* The ELEMENT CONTAINER is what gets positioned, not .stButton
           inside it. Streamlit wraps every element in an
           stElementContainer that is itself `position: relative`, so an
           absolutely-positioned .stButton anchors to that wrapper and
           never leaves the card's normal flow — verified in the DOM
           after the first attempt did exactly that. The wrapper is
           addressable because the button was given a key, which stamps
           `st-key-detailbtn-<TICKER>` onto it. */
        [class*="st-key-focuscard-"] [class*="st-key-detailbtn-"] {{
            position: absolute !important;
            top: 13px;
            right: 14px;
            width: auto !important;
            margin: 0 !important;
            z-index: 2;
        }}
        [class*="st-key-focuscard-"] .stButton {{
            width: auto !important;
            margin: 0 !important;
        }}
        [class*="st-key-focuscard-"] .stButton button {{
            width: 26px !important;
            height: 26px !important;
            min-height: 0 !important;
            padding: 0 !important;
            border-radius: 50% !important;
            border: 1px solid var(--vg-border) !important;
            background: var(--vg-bg) !important;
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
        }}
        [class*="st-key-focuscard-"] .stButton button p {{
            font-size: 16px !important;
            font-weight: 700 !important;
            line-height: 1 !important;
            margin: 0 !important;
            text-transform: none !important;
            letter-spacing: 0 !important;
            color: var(--vg-text-muted) !important;
        }}
        [class*="st-key-focuscard-"] .stButton button:hover {{
            border-color: var(--vg-accent) !important;
            background: var(--vg-accent-soft) !important;
        }}
        [class*="st-key-focuscard-"] .stButton button:hover p {{
            color: var(--vg-accent) !important;
        }}

        /* ---- Detail modal ------------------------------------------
           The dialog's own "Detail" heading is hidden ("do we need the word detail at the top?"). st.dialog
           requires a non-empty title at DECORATION time and it can't be
           made dynamic per call, so the title stays in the Python and
           is hidden here. The close (×) button is a sibling of this h2
           and is deliberately untouched. */
        .stDialog section > h2 {{
            display: none !important;
        }}
        /* Streamlit hard-codes the close button at top:26px, which with
           the title hidden left it sitting 8px BELOW the header row's
           centre line — measured, not guessed. 18px puts its centre on
           the same line as the ticker and the Y!/G chips. */
        .stDialog section > button {{
            top: 18px !important;
        }}

        /* The dialog stacks header and scale as two Streamlit blocks, and
           Streamlit's default 16px gap between them was most of the 22px
           of dead space above the scale (measured). The scale carries its
           own internal breathing room, so it doesn't need a block gap on
           top of that. Bottom padding is left alone — 24px there reads as
           deliberate padding rather than a gap. */
        .stDialog [data-testid="stVerticalBlock"] {{
            gap: 4px !important;
        }}
        .vg-modal-head {{
            display: flex;
            align-items: center;
            gap: 9px;
            margin-bottom: 0;
            /* Clears the dialog's own × close button, which is absolutely
               positioned in the same top-right corner — without this the
               Google chip sits underneath it. */
            padding-right: 42px;
        }}
        .vg-modal-ticker {{
            font-size: 19px;
            font-weight: 800;
        }}
        .vg-modal-co {{
            font-size: 12.5px;
            color: var(--vg-text-muted);
        }}
        .vg-modal-links {{
            display: inline-flex;
            gap: 6px;
            margin-left: auto;
        }}
        /* Compact brand-marked chips, replacing two full-width
           "Yahoo Finance ↗" / "Google Finance ↗" buttons. Brand letters
           rather than logos: st.html() strips <svg>, and an external
           <img> would add a network dependency to a local tool. */
        .vg-ext {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 26px;
            height: 26px;
            border-radius: 50%;
            font-size: 11px;
            font-weight: 800;
            text-decoration: none !important;
            border: 1px solid var(--vg-border);
            transition: background 120ms ease, border-color 120ms ease;
        }}
        .vg-ext-y {{ color: #6001d2 !important; }}
        .vg-ext-g {{ color: #1a73e8 !important; }}
        .vg-ext-y:hover {{ background: #f3ebff; border-color: #6001d2; }}
        .vg-ext-g:hover {{ background: #e8f0fe; border-color: #1a73e8; }}

        /* Compacting for anything Streamlit still renders in the dialog. */
        [data-testid="stDialog"] [data-testid="stMetricValue"],
        [data-testid="stDialog"] [data-testid="stMetricValue"] > div {{
            font-size: 20px !important;
            line-height: 1.25 !important;
        }}
        [data-testid="stDialog"] [data-testid="stMetricLabel"],
        [data-testid="stDialog"] [data-testid="stMetricLabel"] * {{
            font-size: 10px !important;
            font-weight: 600 !important;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: var(--vg-text-muted) !important;
        }}
        [data-testid="stDialog"] h2,
        [data-testid="stDialog"] h3 {{
            font-size: 15px !important;
            margin-bottom: 0 !important;
        }}
        [data-testid="stDialog"] [data-testid="stLinkButton"] a {{
            font-size: 11.5px !important;
            font-weight: 600 !important;
            padding: 3px 10px !important;
            min-height: 0 !important;
            height: 28px !important;
        }}
        [data-testid="stDialog"] [data-testid="stLinkButton"] a p {{
            font-size: 11.5px !important;
        }}
        [data-testid="stDialog"] [data-testid="stCaptionContainer"],
        [data-testid="stDialog"] [data-testid="stCaptionContainer"] * {{
            font-size: 11px !important;
            line-height: 1.55 !important;
        }}

        /* ---- Expanded detail card ----------------------------------
           Measured against the live DOM before touching anything
           ("when u expand, you see everything big
           and clunky"). The defaults were genuinely oversized for a
           card nested inside a row: metric values 36px in a 54px-tall
           box, metric labels 14px, link buttons 16px type in 420px-wide
           slabs. Everything below is scoped to the focus rows so it
           can't leak into the filter panel or the Methodology page.

           render_detail_card() is only ever called from inside a focus
           row now (the heatmap's click-to-detail path was removed), so
           this scoping covers every place it renders. */
        [class*="st-key-focusrow-"] [data-testid="stExpanderDetails"] {{
            padding: 12px 4px 4px 4px !important;
        }}
        /* Vertical rhythm inside the card — Streamlit's default 16px
           block gap is what made it feel airy-but-loose. */
        [class*="st-key-focusrow-"] [data-testid="stExpanderDetails"] [data-testid="stVerticalBlock"] {{
            gap: 8px !important;
        }}
        [class*="st-key-focusrow-"] [data-testid="stExpanderDetails"] h2,
        [class*="st-key-focusrow-"] [data-testid="stExpanderDetails"] h3 {{
            font-size: 15px !important;
            margin-bottom: 0 !important;
        }}
        [class*="st-key-focusrow-"] [data-testid="stMetricValue"] {{
            font-size: 20px !important;
            line-height: 1.25 !important;
        }}
        [class*="st-key-focusrow-"] [data-testid="stMetricValue"] > div {{
            font-size: 20px !important;
        }}
        /* Metric labels styled like the mockup's card footer: tiny,
           uppercase, muted — a label, not a competing headline. */
        [class*="st-key-focusrow-"] [data-testid="stMetricLabel"],
        [class*="st-key-focusrow-"] [data-testid="stMetricLabel"] * {{
            font-size: 10px !important;
            font-weight: 600 !important;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: var(--vg-text-muted) !important;
        }}
        [class*="st-key-focusrow-"] [data-testid="stLinkButton"] a {{
            font-size: 11.5px !important;
            font-weight: 600 !important;
            padding: 3px 10px !important;
            min-height: 0 !important;
            height: 28px !important;
        }}
        [class*="st-key-focusrow-"] [data-testid="stLinkButton"] a p {{
            font-size: 11.5px !important;
        }}
        [class*="st-key-focusrow-"] [data-testid="stExpanderDetails"] [data-testid="stCaptionContainer"],
        [class*="st-key-focusrow-"] [data-testid="stExpanderDetails"] [data-testid="stCaptionContainer"] * {{
            font-size: 11px !important;
            line-height: 1.55 !important;
        }}
        /* Breathing room around the "+ DETAIL" chip — it sat flush
           against the scale above it and the card edge below. */
        [class*="st-key-focusrow-"] [data-testid="stExpander"] {{
            margin-top: 4px !important;
        }}

        /* ---- Brand header ------------------------------------------
           The Option 3 mockup's most distinctive "this is a product"
           signal was a restrained nav strip: a small mark, an 18px
           wordmark, a hairline rule underneath. The app had replaced
           that with a 44px emoji st.title, which is most of why it
           still read as a script's output rather than a product.

           The mark is three CSS bars, NOT the mockup's <svg> — both
           st.html() and st.markdown() sanitize <svg> out of existence
           (the same lesson as the price scale, which had to be rebuilt
           from <div>s for exactly this reason). Three divs render
           identically here and can't be stripped. */
        /* The nav row is st.columns now (brand | meta | Methodology
           link), so the hairline rule lives on the container wrapping
           them rather than on a single html block. */
        [class*="st-key-navrow"] {{
            padding: 2px 0 8px 0;
            border-bottom: 1px solid var(--vg-border);
            margin-bottom: 2px;
        }}
        [class*="st-key-navrow"] [data-testid="stVerticalBlock"] {{
            gap: 0 !important;
        }}
        .vg-brand {{ display: flex; align-items: center; gap: 10px; }}
        .vg-mark {{ display: flex; align-items: flex-end; gap: 3px; height: 18px; }}
        .vg-mark span {{
            width: 4px;
            border-radius: 1px;
            background: var(--vg-accent);
            display: block;
        }}
        .vg-wordmark {{
            font-size: 18px;
            font-weight: 800;
            letter-spacing: -0.01em;
            color: var(--vg-text);
        }}
        .vg-nav-meta {{
            font-size: 12px;
            color: var(--vg-text-muted);
            font-weight: 500;
            text-align: right;
        }}
        /* The disclaimer, demoted from a 144px yellow st.warning slab at
           the very top of the page to one quiet line — the mockup's
           treatment. The full text still lives at the bottom of the
           page and on the Methodology page; nothing was deleted, it
           just stopped being the first thing you see. */
        /* Methodology link — small, right-aligned, sharing a row with
           the fine print under the header. Sized to read as a quiet
           nav link, the way the Option 3 mockup's header links did,
           not as a button. */
        /* width:100% is what makes justify-content:flex-end actually do
           anything. The anchor is shrink-to-fit by default,
           so it measured 73px sitting at the LEFT of a 142px column with
           69px of dead space to its right — the link was right-aligned
           in name only, which is what kept reading as "still off". */
        /* The stElementContainer wrapping the link is a FLEX ITEM inside
           the column's stVerticalBlock, so it shrank to its content
           (73px) inside a 104px column — which meant width:100% further
           down resolved against 73px and the link never reached the
           right edge. Stretching the container is the fix; the two
           rules below then have a full-width box to align within. */
        [class*="st-key-methodology-link"] [data-testid="stElementContainer"] {{
            width: 100% !important;
            align-self: stretch !important;
        }}
        [class*="st-key-methodology-link"] [data-testid="stPageLink"] {{
            width: 100% !important;
        }}
        [class*="st-key-methodology-link"] [data-testid="stPageLink"] a {{
            width: 100% !important;
            justify-content: flex-end;
            padding: 0 !important;
            background: transparent !important;
        }}
        [class*="st-key-methodology-link"] [data-testid="stPageLink"] a p {{
            font-size: 11.5px !important;
            font-weight: 600 !important;
            color: var(--vg-text-muted) !important;
        }}
        [class*="st-key-methodology-link"] [data-testid="stPageLink"] a:hover p {{
            color: var(--vg-accent) !important;
            text-decoration: underline;
        }}

        .vg-fineprint {{
            font-size: 11.5px;
            color: var(--vg-text-muted);
            line-height: 1.6;
        }}
        .vg-footer {{
            /* Was 40px margin + 16px padding, which measured 50px from the
               last card to the rule and 19px from the rule to the text
               (both). The block gap above
               already contributes, so the margin doesn't need to carry
               the whole separation. */
            margin-top: 16px;
            padding-top: 10px;
            border-top: 1px solid var(--vg-border);
            font-size: 11.5px;
            color: var(--vg-text-muted);
            line-height: 1.7;
        }}

        /* Type scale — Streamlit's default h2/h3 render at 28px, ~30%
           larger than the mockup's 21px section headings.

           padding-bottom trimmed from Streamlit's 16px to 4px so a
           section's caption sits WITH its heading instead of floating
           halfway to the content below it. */
        [data-testid="stMainBlockContainer"] h2,
        [data-testid="stMainBlockContainer"] h3 {{
            font-size: 21px !important;
            font-weight: 800 !important;
            letter-spacing: -0.01em !important;
            padding-top: 0 !important;
            padding-bottom: 4px !important;
        }}

        /* ...except the panel heading inside the filter form, where the
           next thing down is a widget LABEL rather than a caption. At
           4px "Filters" collided with "Market cap range"; a caption can
           sit tight under its heading, a control label needs air. */
        [data-testid="stForm"] h2,
        [data-testid="stForm"] h3 {{
            font-size: 11px !important;
            font-weight: 700 !important;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            color: var(--vg-text-muted) !important;
            padding: 0 !important;
            margin: 0 0 8px 0 !important;
            line-height: 1.2 !important;
        }}

        /* Section dividers. Streamlit ships these at 32px top AND
           bottom; combined with the 16px block gap on either side that
           put ~80px of near-empty space between the filter panel and
           the Opportunity Map heading (this
           region directly). 16px reads as a section break without the
           dead air. */
        [data-testid="stMainBlockContainer"] hr {{
            margin: 8px 0 !important;
        }}
        /* Streamlit stacks top-level page blocks with a 16px gap. With a
           divider between two of them that compounded into ~48px between
           the filter panel and the Opportunity Map heading (measured:
           16 + 16 + 16). 10px keeps the sections distinct without the
           drift. Scoped to the DIRECT child stack so nested blocks —
           cards, the dialog, the form — keep the tighter gaps set for
           them elsewhere. */
        [data-testid="stMainBlockContainer"] > [data-testid="stVerticalBlock"] {{
            gap: 10px !important;
        }}
        </style>
        """
        ),
        unsafe_allow_html=True,
    )
