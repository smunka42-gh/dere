"""
Vantage Screener — Disclaimer page.

Fuller, more formal risk-disclosure language than the one-line note in
the nav row and the short paragraph in the footer — this is what those
link to for anyone who wants the complete picture before relying on
anything the site shows.
"""

import streamlit as st

from theme import APP_NAME, inject_theme_css

# Each file under pages/ is its own independent Streamlit script — the
# CSS injected in app.py does NOT carry over here, so this page needs
# its own set_page_config()/inject_theme_css() call, same as app.py.
st.set_page_config(page_title=f"{APP_NAME} — Disclaimer", page_icon="⚠️", layout="centered")
inject_theme_css(wide=False)

with st.container(key="back-link-disclaimer-top"):
    st.page_link("app.py", label="← Back to Vantage Screener")

st.title("Disclaimer")

st.markdown(f"""
### Not investment advice

{APP_NAME} is a personal screening tool, not a source of investment
advice. It applies one published set of rules to public market
data and shows whichever stocks currently match — the same rules and
the same output for every visitor, with no knowledge of your finances,
goals, risk tolerance, or holdings. Nothing on this site is tailored to
you individually, and nothing here should be read as a recommendation
to buy, sell, or hold any security.

### No professional relationship

Using this site does not create an advisory, fiduciary, or any other
professional relationship between you and the person who built it. It
is not produced or reviewed by a licensed financial advisor, broker, or
analyst, and is not registered with any financial regulator.

### Data accuracy is not guaranteed

Prices, analyst targets, and every other figure on this site come from
Yahoo Finance through an **unofficial, unsupported** library. Data can
be delayed, incomplete, or simply wrong, and its availability isn't
guaranteed. Verify anything important against a primary source before
acting on it.

### Past patterns don't predict future results

The screening criteria here look at how a stock has traded historically
relative to its own recent average, its 52-week range, and analyst
targets. None of that predicts what a stock will do next. Markets carry
real risk of loss, and a stock matching this site's criteria today can
still lose value tomorrow.

### Use at your own risk

This site, its data, and its output are provided "as is," with no
warranty of any kind — express or implied — including accuracy,
completeness, or fitness for any particular purpose. To the fullest
extent the law allows, the person who built this tool is not liable for
any loss or damage arising from its use, including decisions made based
on anything it shows.

### Independent research

Treat everything here as a starting point for your own research, not a
substitute for it — and consider talking to a qualified, licensed
financial professional before making investment decisions.
""")

with st.container(key="back-link-disclaimer-bottom"):
    st.page_link("app.py", label="← Back to Vantage Screener")
