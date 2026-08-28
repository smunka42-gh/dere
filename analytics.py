"""
Vantage — lightweight in-memory usage tracking.

Deliberately NOT a third-party analytics package. Both streamlit-analytics
and its maintained fork streamlit-analytics2 hard-require
google-cloud-firestore even in their in-memory mode — a heavy dependency
chain (grpc, protobuf, google-auth, ...) pulled in just to sit unused,
for tracking that amounts to a handful of counters.

Counts live in a plain module-level dict. Streamlit Community Cloud runs
this app as a single process shared by every visitor, so that dict is
already effectively "shared storage" — no database needed.

Tradeoff, chosen deliberately: counts reset whenever the process
restarts (every code push, or after ~12 idle hours, when the free tier
puts the app to sleep). Good enough for a rough sense of usage on a
personal tool; not a durable history. A future upgrade path exists if
that's ever needed (write counts to a file and commit it, the same
pattern run_daily_scan.py already uses) but isn't built until it's
actually wanted.

View the counts by adding ?analytics=on to the site's URL. This is a
convenience flag, not an access control — anyone who knows to add it can
see the dashboard. Acceptable here because it only ever exposes click
counts, never user data.
"""

import threading
from collections import defaultdict

import streamlit as st

_lock = threading.Lock()
_counts = {
    "page_views": 0,
    "market_selected": defaultdict(int),
    "filters_applied": 0,
    "card_opens": defaultdict(int),
}


def track_page_view() -> None:
    """
    Counts a page view once per browser session, not once per script
    rerun. Streamlit reruns this entire script on every widget
    interaction, so without the session_state guard a single visitor
    dragging one slider ten times would count as ten "views."
    """
    if st.session_state.get("_counted_page_view"):
        return
    st.session_state["_counted_page_view"] = True
    with _lock:
        _counts["page_views"] += 1


def track_market_selected(market_id: str) -> None:
    with _lock:
        _counts["market_selected"][market_id] += 1


def track_filters_applied() -> None:
    with _lock:
        _counts["filters_applied"] += 1


def track_card_opened(ticker: str) -> None:
    with _lock:
        _counts["card_opens"][ticker] += 1


def is_dashboard_requested() -> bool:
    return st.query_params.get("analytics") == "on"


def render_dashboard() -> None:
    """Rendered INSTEAD OF the normal page when ?analytics=on is present."""
    st.title("Vantage — usage since last restart")
    st.caption(
        "Counts reset whenever the app process restarts (a code push, or "
        "~12 hours with no visitors puts the free tier to sleep). Not a "
        "durable history — see analytics.py."
    )

    # Copied out from behind the lock so the lock isn't held while
    # Streamlit renders — rendering can be slow; incrementing a counter
    # from another session's script run shouldn't have to wait on it.
    with _lock:
        page_views = _counts["page_views"]
        market_selected = dict(_counts["market_selected"])
        filters_applied = _counts["filters_applied"]
        card_opens = dict(_counts["card_opens"])

    col1, col2 = st.columns(2)
    col1.metric("Page views", page_views)
    col2.metric("Filters applied", filters_applied)

    st.subheader("Market switches")
    if market_selected:
        st.dataframe(
            {
                "Market": list(market_selected.keys()),
                "Times selected": list(market_selected.values()),
            },
            hide_index=True,
        )
    else:
        st.caption("No market switches yet.")

    st.subheader("Most-opened tickers")
    if card_opens:
        top = sorted(card_opens.items(), key=lambda kv: kv[1], reverse=True)[:20]
        st.dataframe(
            {"Ticker": [t for t, _ in top], "Opens": [n for _, n in top]},
            hide_index=True,
        )
    else:
        st.caption("No card detail views yet.")
