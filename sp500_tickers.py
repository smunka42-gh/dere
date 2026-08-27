"""
Vantage — fetches the current S&P 500 ticker list.

Why this file exists on its own: the ticker list changes periodically
(companies get added/removed from the index), so this needs to be
re-fetched, not hardcoded once and forgotten.

Source: Wikipedia's community-maintained S&P 500 table. It's free and
reliable in practice, but — same honesty as everywhere else in this
project — it's not an official/guaranteed data feed, just a well-kept
public page. Good enough for a personal tool; would need a proper index
provider if this were ever a commercial product.
"""

import io
import requests
import pandas as pd

WIKIPEDIA_SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"

# 3 companies have TWO share classes both listed as separate S&P 500
# constituents (hence 503 tickers for "500" companies). For each, we drop
# the class ordinary retail investors don't actually trade and keep the
# other — verified per-company, since the letter naming isn't consistent:
# Alphabet's non-voting class is "GOOG" (keep), its voting class is
# "GOOGL" (drop). Fox Corp and News Corp are the opposite of what the
# letter suggests: the Murdoch family holds voting control through "FOX"
# / "NWS", while "FOXA" / "NWSA" are the widely-traded, effectively
# non-voting classes — so those are the ones kept.
DUPLICATE_SHARE_CLASSES_TO_DROP = {"GOOGL", "FOX", "NWS"}


def get_sp500_tickers() -> list[str]:
    """
    Returns the current list of S&P 500 ticker symbols, e.g. ['MMM', 'AOS', ...].

    Implementation note: we fetch the page ourselves with `requests`
    first, then hand the HTML text to pandas — rather than letting
    pandas.read_html fetch the URL directly. That's a workaround for a
    real SSL certificate error we hit using pandas' direct URL fetching
    on this machine (a known quirk of the python.org macOS installer,
    not specific to this project) — `requests` doesn't have the same
    problem, since it ships its own trusted certificate bundle.
    """
    response = requests.get(WIKIPEDIA_SP500_URL, headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()  # crash loudly if the page didn't load, rather than silently returning garbage

    tables = pd.read_html(io.StringIO(response.text))
    sp500_table = tables[0]  # the first table on the page is the constituent list

    # Yahoo Finance uses a hyphen for share-class tickers (e.g. "BRK-B"),
    # but Wikipedia's table uses a period (e.g. "BRK.B") — without this
    # fix, any ticker with multiple share classes would fail to look up.
    tickers = sp500_table["Symbol"].str.replace(".", "-", regex=False).tolist()

    tickers = [t for t in tickers if t not in DUPLICATE_SHARE_CLASSES_TO_DROP]

    return tickers


if __name__ == "__main__":
    tickers = get_sp500_tickers()
    print(f"Fetched {len(tickers)} tickers.")
    print(tickers[:10], "...")
