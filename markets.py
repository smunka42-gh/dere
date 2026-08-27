"""
Vantage — equity market/universe definitions.

A "market" bundles everything that differs between equity universes:
where to fetch its ticker list, what currency its prices are quoted in,
what market-cap scale is meaningful for it, and where its scan results
are saved. Everything else in the app — the scoring logic, the heatmap,
the cards, the price scale — is written to be market-agnostic; it just
asks a Market object for a currency symbol or a cap threshold rather than
assuming dollars.

Adding a new market means adding one Market entry here plus a ticker
fetcher module (see nifty50_tickers.py for the pattern) — nothing in
app.py, theme.py, or recommendation_logic.py should need to change.
"""

from dataclasses import dataclass
from collections.abc import Callable


@dataclass(frozen=True)
class Market:
    id: str                              # "sp500" — used in the scan filename and the URL's ?market= param
    display_name: str                    # "S&P 500" — shown in the UI
    currency_symbol: str                 # "$"
    fetch_tickers: Callable[[], list[str]]
    scan_output_file: str                # relative to output/
    format_cap: Callable[[float], str]   # e.g. 1.69e12 -> "$1.69T"

    # Market-cap slider checkpoints, as (label, raw value in the local
    # currency) — the same convention yfinance's own marketCap field
    # uses (a plain number, not "in billions").
    cap_range_options: list[tuple[str, float]]
    default_cap_range: tuple[str, str]

    # Absolute thresholds for the Large/Mid/Small cap classification
    # (recommendation_logic.classify_market_cap). Deliberately a rough,
    # commonly-cited heuristic rather than a precise standard — real
    # classifiers (AMFI's for India, various providers' for the US) use
    # a moving RANK cutoff (e.g. "top 100 companies"), not a fixed
    # dollar/rupee line, and are revised periodically. Good enough for a
    # personal screener; not something to cite as authoritative.
    cap_tier_large: float
    cap_tier_mid: float
    cap_tier_small: float

    def format_market_cap(self, market_cap: float | None) -> str:
        """Human-readable market cap in this market's own convention."""
        if market_cap is None:
            return "cap n/a"
        return self.format_cap(market_cap)


def _format_cap_usd(market_cap: float) -> str:
    if market_cap >= 1_000_000_000_000:
        return f"${market_cap / 1_000_000_000_000:.2f}T"
    if market_cap >= 1_000_000_000:
        return f"${market_cap / 1_000_000_000:.1f}B"
    return f"${market_cap / 1_000_000:.0f}M"


def _format_cap_inr(market_cap: float) -> str:
    # Indian financial media quotes company market cap in CRORE (1 Cr =
    # 1e7), not "in billions" — a number expressed in crore is what an
    # Indian user actually recognises. This uses plain Western thousands
    # commas on the crore figure (e.g. "₹10,95,722" would be the correct
    # Indian digit grouping; this prints "₹1,095,722 Cr" instead) — a
    # known simplification, not an attempt at full Indian numbering.
    crore = market_cap / 10_000_000
    return f"₹{crore:,.0f} Cr"


def _lazy_get_sp500_tickers() -> list[str]:
    # Imported inside the function, not at module load — the ticker
    # fetchers hit a real network request (Wikipedia), which a plain
    # `from sp500_tickers import get_sp500_tickers` at the top of this
    # file would still avoid running, but keeping the import itself
    # local makes it obvious neither fetcher runs just from importing
    # `markets`.
    from sp500_tickers import get_sp500_tickers
    return get_sp500_tickers()


def _lazy_get_nifty50_tickers() -> list[str]:
    from nifty50_tickers import get_nifty50_tickers
    return get_nifty50_tickers()


SP500 = Market(
    id="sp500",
    display_name="S&P 500",
    currency_symbol="$",
    fetch_tickers=_lazy_get_sp500_tickers,
    scan_output_file="latest_scan_sp500.json",
    format_cap=_format_cap_usd,
    cap_range_options=[
        ("$300M", 300_000_000), ("$500M", 500_000_000),
        ("$1B", 1_000_000_000), ("$2B", 2_000_000_000), ("$5B", 5_000_000_000),
        ("$10B", 10_000_000_000), ("$20B", 20_000_000_000), ("$50B", 50_000_000_000),
        ("$100B", 100_000_000_000), ("$200B", 200_000_000_000), ("$500B", 500_000_000_000),
        ("$1T", 1_000_000_000_000), ("$2T", 2_000_000_000_000),
        ("$5T", 5_000_000_000_000), ("$10T", 10_000_000_000_000),
    ],
    default_cap_range=("$100B", "$10T"),
    cap_tier_large=10_000_000_000,
    cap_tier_mid=2_000_000_000,
    cap_tier_small=300_000_000,
)

NIFTY50 = Market(
    id="nifty50",
    display_name="Nifty 50",
    currency_symbol="₹",
    fetch_tickers=_lazy_get_nifty50_tickers,
    scan_output_file="latest_scan_nifty50.json",
    format_cap=_format_cap_inr,
    cap_range_options=[
        ("₹1,000 Cr", 10_000_000_000), ("₹5,000 Cr", 50_000_000_000),
        ("₹10,000 Cr", 100_000_000_000), ("₹25,000 Cr", 250_000_000_000),
        ("₹50,000 Cr", 500_000_000_000), ("₹1,00,000 Cr", 1_000_000_000_000),
        ("₹2,50,000 Cr", 2_500_000_000_000), ("₹5,00,000 Cr", 5_000_000_000_000),
        ("₹10,00,000 Cr", 10_000_000_000_000), ("₹20,00,000 Cr", 20_000_000_000_000),
    ],
    # Every Nifty 50 constituent is, by the index's own definition, among
    # the largest ~50 companies on the exchange — unlike the S&P 500
    # default (deliberately restricted to mega-caps within a much larger
    # 500-company universe), there's no similarly-motivated reason to
    # pre-filter this index further by cap. Defaults to the full range;
    # the rating and Composite Upside filters do the real narrowing.
    default_cap_range=("₹1,000 Cr", "₹20,00,000 Cr"),
    cap_tier_large=1_000_000_000_000,   # ₹1,00,000 Cr
    cap_tier_mid=250_000_000_000,       # ₹25,000 Cr
    cap_tier_small=50_000_000_000,      # ₹5,000 Cr
)

MARKETS: dict[str, Market] = {SP500.id: SP500, NIFTY50.id: NIFTY50}
DEFAULT_MARKET_ID = SP500.id
