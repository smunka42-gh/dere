"""
Vantage — fetches the current Nifty 50 ticker list (NSE, India).

Same pattern as sp500_tickers.py: scrape Wikipedia's community-maintained
constituent table rather than hardcode it, since index membership changes
periodically.

Source: Wikipedia's NIFTY 50 page. Same honesty as everywhere else in this
project — it's not an official/guaranteed data feed, just a well-kept
public page.
"""

import io
import requests
import pandas as pd

WIKIPEDIA_NIFTY50_URL = "https://en.wikipedia.org/wiki/NIFTY_50"

# yfinance expects NSE tickers with a ".NS" suffix (e.g. "RELIANCE.NS").
# Wikipedia's table lists the bare NSE symbol, so it needs appending here.
NSE_SUFFIX = ".NS"


def get_nifty50_tickers() -> list[str]:
    """
    Returns the current list of Nifty 50 ticker symbols in yfinance's
    format, e.g. ['RELIANCE.NS', 'TCS.NS', ...].
    """
    response = requests.get(WIKIPEDIA_NIFTY50_URL, headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()

    tables = pd.read_html(io.StringIO(response.text))
    # The constituent table is the one with a "Symbol" column — its
    # position on the page isn't as fixed as S&P 500's (there are more
    # tables above it, e.g. index history), so it's found by column name
    # rather than assumed to be tables[0].
    constituents = next(t for t in tables if "Symbol" in t.columns)

    symbols = constituents["Symbol"].dropna()
    tickers = [f"{s}{NSE_SUFFIX}" for s in symbols]

    return tickers


if __name__ == "__main__":
    tickers = get_nifty50_tickers()
    print(f"Fetched {len(tickers)} tickers.")
    print(tickers[:10], "...")
