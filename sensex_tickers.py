"""
Vantage — fetches the current BSE SENSEX ticker list, priced via NSE.

Same pattern as sp500_tickers.py and nifty50_tickers.py: scrape
Wikipedia's community-maintained constituent table rather than hardcode
it, since index membership changes periodically.

Source of INDEX MEMBERSHIP (which 30 companies): Wikipedia's BSE SENSEX
page. Same honesty as everywhere else in this project — it's not an
official/guaranteed data feed, just a well-kept public page.

Source of PRICE DATA: NSE (".NS" tickers), not BSE (".BO"), even though
this is nominally the BSE index. Verified directly against yfinance:
every ".BO" ticker returns exactly ONE row of price history regardless
of the requested period (`period="1y"` gives 1 row; explicit start/end
dates give 0 and "possibly delisted") — Yahoo's own BSE data feed is
essentially empty. The identical company's ".NS" listing returns a full
year of real trading days. All 30 Sensex constituents are confirmed
dual-listed on NSE, so this fetches the Wikipedia page for INDEX
MEMBERSHIP only, then swaps each symbol's exchange suffix before
returning it — the tickers this app actually evaluates are NSE-priced,
not BSE-priced, which is a deliberate, necessary substitution, not an
oversight.
"""

import io
import requests
import pandas as pd

WIKIPEDIA_SENSEX_URL = "https://en.wikipedia.org/wiki/BSE_SENSEX"


def get_sensex_tickers() -> list[str]:
    """
    Returns the current Sensex constituent list as NSE-priced yfinance
    tickers, e.g. ['RELIANCE.NS', 'HDFCBANK.NS', ...] — see module
    docstring for why ".NS" rather than the nominal ".BO".
    """
    response = requests.get(WIKIPEDIA_SENSEX_URL, headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()

    tables = pd.read_html(io.StringIO(response.text))
    # The table's "Symbol" column carries the ".BO" suffix as published
    # (e.g. "RELIANCE.BO") — swapped to ".NS" below.
    constituents = next(t for t in tables if "Symbol" in t.columns)

    symbols = constituents["Symbol"].dropna()
    tickers = [s.replace(".BO", ".NS") for s in symbols]

    return tickers


if __name__ == "__main__":
    tickers = get_sensex_tickers()
    print(f"Fetched {len(tickers)} tickers.")
    print(tickers[:10], "...")
