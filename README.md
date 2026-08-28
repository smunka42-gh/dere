# Vantage Screener

A single-page stock screener over two equity markets — S&P 500 and Nifty
50. It ranks companies by a blended **Composite Upside %** — a weighted
mix of upside to a moving average, to the 52-week high, and to the
analyst median target — so a daily glance is enough to see whether
anything is worth a closer look.

**Live:** https://vantagescreener.streamlit.app/

## How it works

A nightly scan (`run_daily_scan.py`) fetches every ticker in every
configured market once and writes one JSON file per market
(`output/latest_scan_<market>.json` — see `markets.py`). The app reads
only the file for the selected market, so filters re-score its tickers as
pure arithmetic with no live API calls. A scheduled GitHub Action
refreshes the data each weekday at 17:00 New York time, one hour after
the US market close.

See [DESIGN_DOC.md](DESIGN_DOC.md) for the architecture, the scoring
methodology, and the Streamlit constraints worth knowing before changing
the UI.

## Running locally

```bash
pip install -r requirements.txt
streamlit run app.py          # the site
python run_daily_scan.py      # refresh the data
```

## Data source

Price history, analyst targets and recommendation counts come from Yahoo
Finance via the unofficial [`yfinance`](https://github.com/ranaroussi/yfinance)
library — not guaranteed accurate, complete, or continuously available.

## Not financial advice

This tool encodes one person's personal rules in software. It is not
professional investment advice, is not from a licensed advisor, and
should be used at your own risk.
