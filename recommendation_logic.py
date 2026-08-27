"""
Vantage — core recommendation logic.

This file is being tested on a SMALL list of well-known tickers first,
before we scale up to the full S&P 500. That's deliberate: we want to see
real numbers come out and sanity-check them before trusting this logic
on 500 stocks at once.

Every function here is written to be read, not just run — comments explain
the "why" behind each step, not just the "what", since this is meant to be
understandable by someone reading Python for the first time.
"""

import yfinance as yf
import pandas as pd

# Yahoo's short exchange codes -> what Google Finance's URL scheme
# expects. Covers every exchange this app's markets actually fetch from
# (S&P 500 tickers, plus NSE for Nifty 50); anything else is left
# unmapped rather than guessed.
GOOGLE_FINANCE_EXCHANGE_MAP = {
    "NMS": "NASDAQ",  # Nasdaq Global Select
    "NGM": "NASDAQ",  # Nasdaq Global Market
    "NCM": "NASDAQ",  # Nasdaq Capital Market
    "NYQ": "NYSE",
    "ASE": "NYSEAMERICAN",
    "NSI": "NSE",      # National Stock Exchange of India — yfinance's ".NS" tickers
}


SMA_WINDOW_DAYS = 100  # ~5 months. Chosen after comparing 20/50/100/200-day windows on real tickers — smooth enough to require a genuine, sustained pullback (not just short-term noise), recent enough to avoid dragging in a stale, no-longer-relevant price regime. Still the DEFAULT window; kept as a locked-in choice, not removed — see SMA_WINDOW_OPTIONS below for the full adjustable range.

# The set of windows the website's SMA slicer lets you pick between
# narrowed from [20, 50, 100, 200] to
# just [50, 200] per his follow-up ("let's stick to 50 and 200 day avgs
# only"), matching the two windows Yahoo Finance itself publishes
# directly (fiftyDayAverage / twoHundredDayAverage — confirmed via a
# live check; Yahoo has no 20-day or 100-day field at all). Every
# option here still gets independently COMPUTED and saved during the
# batch scan (not read from Yahoo's own fields — see
# build_price_scale_html() in app.py for why: Yahoo's numbers don't
# exactly match ours, which would make the price-scale visualization
# disagree with the Composite Upside % math on the same card), so the
# slicer can switch instantly rather than recomputing 500+ tickers'
# price history live every time someone moves it.
SMA_WINDOW_OPTIONS = [50, 200]


def compute_recent_average_price(daily_closes: pd.Series, window_days: int = SMA_WINDOW_DAYS) -> float:
    """
    A simple moving average (SMA) over the most recent `window_days`
    trading days — the standard, widely-used technical-analysis concept
    (the "100-day moving average"), not a custom invention.

    Supersedes an earlier "mode price" approach (histogram/bucket-based,
    picking whichever 1%-wide price band collected the most days across
    the full 12 months). Dropped after a a concern about relevance:
    that approach only ever used a handful of days (as few as 10 out of
    ~252 for some tickers) — a narrow coincidence, not a genuinely
    "large number of days" as intended, and it could anchor on a stale
    regime from many months ago. A 100-day rolling average fixes both:
    it always uses exactly 100 real days, and it's inherently recent
    (a rolling window, not a fixed year).

    Arguments:
        daily_closes: a pandas Series of closing prices, one per trading day.
        window_days: how many of the most recent trading days to average.

    Returns:
        The average closing price over the last `window_days` days.
    """
    # Same NaN-safety reasoning as elsewhere in this file: a missing
    # day's price shouldn't be silently guessed at, just excluded.
    daily_closes = daily_closes.dropna()
    recent_window = daily_closes.tail(window_days)
    return float(recent_window.mean())


_CORPORATE_SUFFIXES = [
    ", inc.", " inc.", " inc", ", inc",
    " corporation", " corp.", " corp",
    " co.", ", ltd.", " ltd.", " ltd",
    " plc", " holdings", " company", " group",
]


def _extract_brand_name(company_name: str) -> str:
    """
    Turn a formal legal name like "Meta Platforms, Inc." into the word
    a news headline would actually use: "Meta".

    Real bug found during validation: checking whether the FULL legal
    name ("Meta Platforms, Inc.") appears in a headline almost never
    matches, because headlines say "Meta", not the legal entity name.
    This strips common corporate suffixes, then takes the first
    remaining word — a heuristic, not perfect (e.g. "The Home Depot"
    would extract "The", which is useless), but correctly handles the
    common case of well-known single/double-word brand names.
    """
    cleaned = company_name.lower()
    for suffix in _CORPORATE_SUFFIXES:
        cleaned = cleaned.replace(suffix, "")
    cleaned = cleaned.strip().rstrip(",").strip()
    first_word = cleaned.split(" ")[0] if cleaned else ""
    return first_word


def get_latest_relevant_headline(
    ticker, company_name: str | None, ticker_symbol: str | None = None
) -> tuple[str | None, str | None, bool]:
    """
    Get the most recent news headline that's ACTUALLY about this company.

    Three real problems with yfinance's raw `ticker.news` list, ALL
    discovered by inspecting real output during validation, not assumed
    up front:
    1. It is NOT sorted by publish date — item 0 is not reliably the
       newest story.
    2. It mixes in general market/sector news (e.g. a competitor's
       earnings, broad market index updates) that isn't specific to
       this company at all.
    3. Matching on the FULL legal company name (e.g. "Meta Platforms,
       Inc.") essentially never matches real headlines, which use the
       brand name instead (e.g. "Meta"). This was a real bug in an
       a previous approach — it looked like it worked
       because the fallback path happened to coincidentally pick
       relevant news, not because the filter actually matched anything.

    Fix: extract the brand name from the company name (see
    _extract_brand_name), match on that OR the ticker symbol, sort
    what's left by actual publish date, take the most recent. If
    nothing matches, fall back to the single most recent headline
    overall (better than nothing) — but that fallback is genuinely
    general market news, not a company-specific signal.

    Returns (headline_title, published_date, is_company_specific).
    Title/date are None if there's no news at all; is_company_specific
    is False when we had to fall back to general market news.
    """
    try:
        news_items = ticker.news
    except Exception:
        # News is a "nice to have" signal, not core to the recommendation
        # if fetching it fails for any reason, don't let that break the
        # whole evaluation for this ticker.
        return None, None, False

    if not news_items:
        return None, None, False

    # Normalize each item to a simple (title, pubDate) pair first.
    parsed_items = []
    for item in news_items:
        content = item.get("content", item)
        title = content.get("title")
        pub_date = content.get("pubDate")
        if title and pub_date:
            parsed_items.append((title, pub_date))

    if not parsed_items:
        return None, None, False

    # Filter to headlines that mention the company's brand name (not the
    # full legal name — see _extract_brand_name for why) or the ticker
    # symbol itself, which headlines sometimes include directly.
    brand_name = _extract_brand_name(company_name) if company_name else ""
    company_specific = []
    for title, pub_date in parsed_items:
        title_lower = title.lower()
        brand_match = len(brand_name) > 2 and brand_name in title_lower
        ticker_match = ticker_symbol and ticker_symbol.lower() in title_lower
        if brand_match or ticker_match:
            company_specific.append((title, pub_date))

    # Sort by publish date, most recent first. ISO date strings like
    # "T20:45:34Z" sort correctly as plain text, so we don't
    # need to parse them into real datetime objects for this.
    is_company_specific = bool(company_specific)
    candidates = company_specific if company_specific else parsed_items
    candidates.sort(key=lambda pair: pair[1], reverse=True)

    title, pub_date = candidates[0]
    return title, pub_date, is_company_specific


def compute_range_position(most_recent_close: float, daily_closes: pd.Series) -> dict:
    """
    Compute the classic 52-week low/high (the true single-day extremes),
    and where today's close sits on a 0-100 sliding scale between them.

    0 = sitting right at the 52-week low. 100 = sitting right at the
    52-week high. 50 = exactly halfway between.
    """
    low_52w = float(daily_closes.min())
    high_52w = float(daily_closes.max())
    range_52w = high_52w - low_52w

    if range_52w <= 0:
        # Stock didn't move at all in a year — degenerate case, put it
        # in the middle rather than dividing by zero.
        position_pct = 50.0
    else:
        position_pct = (most_recent_close - low_52w) / range_52w * 100

    return {
        "fifty_two_week_low": round(low_52w, 2),
        "fifty_two_week_high": round(high_52w, 2),
        "position_in_range_pct": round(position_pct, 1),
    }


def compute_upside_pct(reference_price: float, current_price: float) -> float:
    """
    Generic "% upside if the price moved from current_price up to
    reference_price" — current_price is always the denominator. This is
    the standard way analyst upside is expressed ("stock has X% upside
    to target"), and it's what corrected the logic to use for
    BOTH deltas ("use upside so denominator should
    be current price"), not just the target-price one.

    Used for several different reference prices that all share this
    same formula: the 52-week high (Delta 1), the analyst target
    (Delta 2), and the 100-day moving average (Composite Upside %'s
    dominant component).

    A negative result means current_price is already above the
    reference (e.g. already above the 52w high, or already above target).
    """
    return (reference_price - current_price) / current_price * 100


# Third logic revision — Composite Upside %, a weighted
# blend of THREE upside measures (replaces the min()/max() two-delta
# system for the recommendations list; the 3 heatmap slices are
# unaffected and still use Delta 1 / Delta 2 / max(Delta 1, Delta 2)
# individually). Weights, chosen and revised in conversation with
# review after comparing real tickers (GOOG, MSFT):
#   50% upside to the 100-day moving average (the dominant signal —
#       requires an actual, sustained pullback, not just short-term noise)
#   25% upside to the 52-week high (single-day peak, can be noisy)
#   25% upside to the analyst median target (the stated view:
#       analyst targets can run "iffy, often inflated")
COMPOSITE_WEIGHT_RECENT_AVG = 0.50
COMPOSITE_WEIGHT_PEAK = 0.25
COMPOSITE_WEIGHT_TARGET = 0.25

# Qualification bar for the Composite Upside % — same 10% used by the
# prior min()-based system, kept as the default; may need revisiting
# once real distribution data comes in for this new metric specifically.
COMPOSITE_UPSIDE_THRESHOLD_PCT = 10

# Histogram-style display bins (not filtering) for stack-ranking
# qualifying results — fixed, human-readable round numbers rather than
# algorithmically-computed bins, so the bin boundaries stay consistent
# day to day instead of shifting based on whatever happens to qualify.
UPSIDE_HISTOGRAM_BINS = [
    (10, 15, "10–15%"),
    (15, 20, "15–20%"),
    (20, 30, "20–30%"),
    (30, 50, "30–50%"),
    (50, float("inf"), "50%+"),
]


def bucket_upside(pct: float) -> str:
    """Which histogram bucket a qualifying stock's Composite Upside % falls into."""
    for low, high, label in UPSIDE_HISTOGRAM_BINS:
        if low <= pct < high:
            return label
    return "Below threshold"


def classify_market_cap(
    market_cap: float | None,
    large_threshold: float,
    mid_threshold: float,
    small_threshold: float,
) -> str | None:
    """
    Classify a company's market capitalization into Large/Mid/Small cap,
    against thresholds supplied by the caller rather than fixed in this
    function — the same absolute number means something very different
    in dollars than in rupees, so there's no single "US thresholds"
    default that would be honest for every market this tool scans. See
    markets.py for the actual per-market values (cap_tier_large/mid/small)
    and why they're a rough heuristic rather than a precise standard.

    Expectation to set: an index's own membership already skews toward
    bigger companies, so most or all results for a given scan will
    likely come back "Large Cap" — that's expected, not a bug.
    """
    if market_cap is None:
        return None
    elif market_cap >= large_threshold:
        return "Large Cap"
    elif market_cap >= mid_threshold:
        return "Mid Cap"
    elif market_cap >= small_threshold:
        return "Small Cap"
    else:
        return "Micro Cap"


# Analyst rating threshold for "strong buy consensus" (logic
# update). Scale is 1.0 (Strong Buy) to 5.0 (Strong Sell). 1.5 is a
# reasonable cutoff for "solidly in Strong Buy territory" — adjustable,
# flagged here rather than buried, same as the other tuned thresholds
# in this file (bucket_pct, the 15% screen).
STRONG_BUY_RATING_THRESHOLD = 1.5


def get_recommendation_breakdown(ticker) -> dict:
    """
    Get the count of analysts in each rating bucket (strong buy / buy /
    hold / sell / strong sell) for the CURRENT month, plus the same
    breakdown for the prior 3 months — so we can see if opinion has been
    shifting recently, not just a single frozen snapshot.

    This is a richer signal than the single 1-5 recommendationMean score
    (which we also keep) — e.g. "8 strong buy, 47 buy, 7 hold, 0 sell"
    tells you much more than "1.35 average".
    """
    try:
        rec_table = ticker.recommendations
    except Exception:
        return {"current_month": None, "trend": []}

    if rec_table is None or rec_table.empty:
        return {"current_month": None, "trend": []}

    # yfinance returns rows labeled "0m" (this month), "-1m", "-2m", "-3m"
    # (prior months) — we grab all of them to show the trend, and treat
    # "0m" as the headline "current" figure.
    trend = []
    current_month = None
    for _, row in rec_table.iterrows():
        snapshot = {
            "period": row.get("period"),
            "strong_buy": int(row.get("strongBuy", 0)),
            "buy": int(row.get("buy", 0)),
            "hold": int(row.get("hold", 0)),
            "sell": int(row.get("sell", 0)),
            "strong_sell": int(row.get("strongSell", 0)),
        }
        trend.append(snapshot)
        if snapshot["period"] == "0m":
            current_month = snapshot

    return {"current_month": current_month, "trend": trend}


def get_live_market_context(info: dict) -> dict:
    """
    Pull whatever live pre-market/post-market data Yahoo currently has
    for this ticker. These fields are only populated during the relevant
    window (e.g. postMarketPrice is only set while the market is
    actually in post-market hours) — outside that window they'll
    legitimately be None, which is expected, not a bug.
    """
    return {
        "market_state": info.get("marketState"),
        "regular_market_price": info.get("regularMarketPrice"),
        "post_market_price": info.get("postMarketPrice"),
        "post_market_change_pct": info.get("postMarketChangePercent"),
        "pre_market_price": info.get("preMarketPrice"),
        "pre_market_change_pct": info.get("preMarketChangePercent"),
    }


def evaluate_ticker(
    ticker_symbol: str,
    cap_tier_large: float = 10_000_000_000,
    cap_tier_mid: float = 2_000_000_000,
    cap_tier_small: float = 300_000_000,
) -> dict | None:
    """
    Run the full evaluation logic for a single stock ticker, end to end:
      1. Pull 12 months of daily price history
      2. Compute the 52w price (our custom "most-visited price" metric)
      3. Compare it to the most recent closing price
      4. Pull the analyst target price and apply the upside filter
      5. Classify into a tier, if it qualifies

    The cap_tier_* arguments are passed straight through to
    classify_market_cap() and default to the S&P 500's own thresholds, so
    existing callers that don't care about other markets keep working
    unchanged — the daily scan script passes each market's own values
    explicitly instead of relying on this default (see markets.py).

    Returns a dict describing the result (whether or not it ended up
    being a recommendation — that's useful for debugging/validation,
    since we want to see the numbers even for stocks that DON'T qualify,
    to sanity-check the math). Returns None only if we couldn't get
    usable data at all for this ticker (e.g. a bad symbol).
    """
    ticker = yf.Ticker(ticker_symbol)

    # auto_adjust=True (the default in this yfinance version, but we set
    # it explicitly so it's obvious) means the "Close" column already
    # accounts for stock splits and dividends — important, since without
    # that adjustment a stock split could look like a huge fake price drop.
    history = ticker.history(period="1y", auto_adjust=True)

    if history.empty:
        print(f"  [{ticker_symbol}] No price history returned — skipping.")
        return None

    # Dropped here, once, rather than trusting every row to be valid —
    # yfinance can return a placeholder row for the current calendar
    # date with a NaN close before that day's data is finalized. Caught
    # on NSE tickers specifically: Yahoo's non-US pipelines appear to
    # lag behind the primary US feed in finalizing a day's close, so a
    # scan run a few hours after the Indian market closes could still
    # see today's row as NaN — that produced a Composite Upside of NaN
    # for every Nifty 50 ticker before this fix. dropna() here means
    # every downstream read of daily_closes (including
    # compute_recent_average_price's own belt-and-suspenders dropna)
    # can simply trust the data it's given.
    daily_closes = history["Close"].dropna()

    if daily_closes.empty:
        print(f"  [{ticker_symbol}] Price history had no usable (non-NaN) closes — skipping.")
        return None

    # "Most recent close" = the actual last trading day in the data,
    # NOT literally calendar-yesterday. This correctly handles Mondays
    # (last trading day is Friday) and holidays automatically, since
    # yfinance simply won't have rows for days the market was closed.
    most_recent_close = float(daily_closes.iloc[-1])
    most_recent_date = daily_closes.index[-1].date()

    # 100-day moving average — the dominant (50%) input to Composite
    # Upside %. See compute_recent_average_price for why this replaced
    # the earlier mode-price/histogram approach.
    recent_avg_price = compute_recent_average_price(daily_closes)
    upside_to_recent_avg = round(compute_upside_pct(recent_avg_price, most_recent_close), 2)

    # Same upside-to-moving-average computation, but for EVERY window in
    # SMA_WINDOW_OPTIONS, not just the default 100-day one above — lets
    # the website's SMA slicer switch instantly between saved values
    # instead of recomputing live. Keyed by window as a STRING (not
    # int) because this dict round-trips through JSON, where object
    # keys are always strings — using strings from the start avoids a
    # silent int/string key mismatch when the saved scan is read back.
    sma_upside_by_window = {}
    for window_days in SMA_WINDOW_OPTIONS:
        window_avg_price = compute_recent_average_price(daily_closes, window_days=window_days)
        sma_upside_by_window[str(window_days)] = round(compute_upside_pct(window_avg_price, most_recent_close), 2)

    # The classic 52-week low/high (true single-day extremes) and where
    # today's close sits between them, 0-100.
    range_position = compute_range_position(most_recent_close, daily_closes)

    # Analyst target price comes from yfinance's `.info` dict, which is
    # a grab-bag of company/market data scraped from Yahoo Finance. This
    # is the most fragile part of the pipeline (per our design doc) —
    # coverage isn't guaranteed for every ticker, so we handle a missing
    # value gracefully instead of crashing.
    #
    # We pull more than just the mean here, for transparency/robustness:
    # targetMeanPrice / targetMedianPrice: two different "consensus"
    #   summaries. Median resists a single extreme analyst skewing the
    #   number; mean is the more commonly-quoted figure. We use mean as
    #   the primary filter for now (matches the original spec) but keep
    #   both visible so it's not a black box.
    # targetHighPrice / targetLowPrice: the full spread of opinion.
    # numberOfAnalystOpinions: how many analysts this is based on —
    #   a target price from 2 analysts means something very different
    #   than one from 50.
    info = ticker.info
    target_mean_price = info.get("targetMeanPrice")
    target_median_price = info.get("targetMedianPrice")
    target_high_price = info.get("targetHighPrice")
    target_low_price = info.get("targetLowPrice")
    num_analysts = info.get("numberOfAnalystOpinions")
    # 1.0 = Strong Buy ... 5.0 = Strong Sell (confirmed directly against
    # real data, e.g. META's 1.35 mapped to recommendationKey
    # "strong_buy") — NOT a 5-star-style scale where 5 is best. Getting
    # this backwards would mean recommending stocks analysts are most
    # bearish on, so it's called out explicitly here, not just assumed.
    recommendation_mean = info.get("recommendationMean")
    recommendation_key = info.get("recommendationKey")
    company_name = info.get("shortName")
    market_cap = info.get("marketCap")
    market_cap_tier = classify_market_cap(market_cap, cap_tier_large, cap_tier_mid, cap_tier_small)
    # Sector comes straight from yfinance's own data (not the S&P 500
    # Wikipedia table) so this works for ANY ticker, not just S&P 500
    # members — needed for the ad-hoc single-ticker search feature.
    sector = info.get("sector")
    # Exchange, for building an external Google Finance link (its URLs
    # need the exchange to resolve reliably, e.g. "GOOGL:NASDAQ" not
    # just "GOOGL"). Yahoo's own short codes (NMS, NYQ, ...) don't match
    # Google's naming, so map the common ones; anything unmapped just
    # omits the exchange suffix rather than guessing wrong.
    exchange_code = info.get("exchange")
    google_finance_exchange = GOOGLE_FINANCE_EXCHANGE_MAP.get(exchange_code)

    # Grab the most recent news headline that's actually about this
    # company (not just general market news), as a qualitative "sanity
    # check" signal — e.g. a big lawsuit settlement announced today can
    # explain an otherwise-confusing price move. We're not scoring
    # sentiment automatically (yet) — just surfacing the raw headline
    # worth noting to read himself. See get_latest_relevant_headline()
    # for why this needs filtering + sorting, not just "take item 0".
    latest_headline, latest_headline_date, headline_is_company_specific = get_latest_relevant_headline(
        ticker, company_name, ticker_symbol
    )

    # Buy/hold/sell analyst breakdown (richer than the single 1-5 mean
    # score) and live pre/post-market price action, if the market is
    # currently in one of those windows.
    recommendation_breakdown = get_recommendation_breakdown(ticker)
    live_market = get_live_market_context(info)

    # Second logic revision — the simplified core
    # intuition, replacing the first revision's mode-based "52w price"
    # comparison: two deltas, both expressed as standard "% upside from
    # current price", combined by taking the LOWER of the two (a
    # conservative "needs room by both measures" signal, fitting for
    # buying in small tranches rather than all at once):
    #   Delta 1: upside if price returns to the classic 52-week HIGH
    #   Delta 2: upside if price reaches the analyst target
    upside_to_52w_high = round(compute_upside_pct(range_position["fifty_two_week_high"], most_recent_close), 2)
    # Delta 2 uses the MEDIAN target rather than the mean: the median
    # resists a single outlier analyst skewing the figure. Falls back to
    # mean only if median is somehow missing but mean isn't (rare —
    # normally both come from the same analyst pool, present or absent
    # together).
    reference_target = target_median_price if target_median_price is not None else target_mean_price

    # max() still powers Heatmap Slice 3 (catches a stock at/above its
    # 52w high — Delta 1 ~0 — that still has huge target upside, which
    # a min()-style combination would hide). min() itself is no longer
    # used anywhere — Composite Upside % (below) replaced it as the
    # recommendations list's qualification + ranking metric.
    upside_to_target = None
    max_upside_signal = None
    if reference_target is not None:
        upside_to_target = round(compute_upside_pct(reference_target, most_recent_close), 2)
        max_upside_signal = max(upside_to_52w_high, upside_to_target)

    # Composite Upside % — weighted blend of three upside
    # measures, only computable once all three are available.
    composite_upside = None
    if upside_to_target is not None:
        composite_upside = round(
            COMPOSITE_WEIGHT_RECENT_AVG * upside_to_recent_avg
            + COMPOSITE_WEIGHT_PEAK * upside_to_52w_high
            + COMPOSITE_WEIGHT_TARGET * upside_to_target,
            2,
        )

    result = {
        "ticker": ticker_symbol,
        "company_name": company_name,
        "market_cap": market_cap,
        "market_cap_tier": market_cap_tier,
        "sector": sector,
        "google_finance_exchange": google_finance_exchange,
        "as_of_date": str(most_recent_date),
        "most_recent_close": round(most_recent_close, 2),
        "recent_avg_price": round(recent_avg_price, 2),
        "upside_to_recent_avg_pct": upside_to_recent_avg,
        "sma_upside_by_window": sma_upside_by_window,
        **range_position,
        "analyst_target_mean": target_mean_price,
        "analyst_target_median": target_median_price,
        "analyst_target_high": target_high_price,
        "analyst_target_low": target_low_price,
        "num_analyst_opinions": num_analysts,
        "recommendation_mean": recommendation_mean,
        "recommendation_key": recommendation_key,
        "upside_to_52w_high_pct": upside_to_52w_high,
        "upside_to_target_pct": upside_to_target,
        "max_upside_signal_pct": max_upside_signal,
        "composite_upside_pct": composite_upside,
        "recommendation_breakdown": recommendation_breakdown,
        "live_market": live_market,
        "latest_headline": latest_headline,
        "latest_headline_date": latest_headline_date,
        "headline_is_company_specific": headline_is_company_specific,
        "tag": None,
        "recommended": False,
        "skip_reason": None,
    }

    if reference_target is None:
        result["skip_reason"] = "No analyst target price available"
        return result

    if recommendation_mean is None:
        result["skip_reason"] = "No analyst rating available"
        return result

    if recommendation_mean > STRONG_BUY_RATING_THRESHOLD:
        result["skip_reason"] = (
            f"Analyst rating ({recommendation_mean:.2f}) not in Strong Buy territory "
            f"(needs ≤{STRONG_BUY_RATING_THRESHOLD})"
        )
        return result

    # No separate "is current price already above target" check needed
    # if it is, upside_to_target comes out negative, which drags down
    # (and can fail) the Composite Upside % threshold below.
    if composite_upside < COMPOSITE_UPSIDE_THRESHOLD_PCT:
        result["skip_reason"] = (
            f"Composite Upside % ({composite_upside:.1f}%, 50% upside-to-100day-avg + "
            f"25% upside-to-52w-high + 25% upside-to-target) below the "
            f"{COMPOSITE_UPSIDE_THRESHOLD_PCT}% bar"
        )
        return result

    result["tag"] = bucket_upside(composite_upside)
    result["recommended"] = True
    return result


if __name__ == "__main__":
    # Small, well-known validation set — NOT the full S&P 500 yet.
    # The point right now is to eyeball real numbers and make sure the
    # logic is doing something sensible before we scale up.
    validation_tickers = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA"]

    print("Running Vantage core logic on validation tickers...\n")

    all_results = []
    for symbol in validation_tickers:
        print(f"Evaluating {symbol}...")
        result = evaluate_ticker(symbol)
        if result is not None:
            all_results.append(result)

    print("\n--- Full results (including non-recommendations, for validation) ---")
    for r in all_results:
        print(r)

    print("\n--- Recommendations only, human-readable ---")
    for r in all_results:
        if r["recommended"]:
            print(f"\n{r['ticker']} — {r['tag'].upper()}")
            print(f"  Close: ${r['most_recent_close']} | 100-day avg: ${r['recent_avg_price']} ({r['upside_to_recent_avg_pct']:+.1f}%) | Composite Upside: {r['composite_upside_pct']:+.1f}%")
            print(f"  52w range: ${r['fifty_two_week_low']}–${r['fifty_two_week_high']} | today sits at {r['position_in_range_pct']}% of that range")
            print(f"  Analyst target: median ${r['analyst_target_median']} (P50), "
                  f"range ${r['analyst_target_low']}–${r['analyst_target_high']} ({r['num_analyst_opinions']} analysts)")
            cm = r["recommendation_breakdown"]["current_month"]
            if cm:
                print(f"  Ratings (this month): {cm['strong_buy']} strong buy, {cm['buy']} buy, "
                      f"{cm['hold']} hold, {cm['sell']} sell, {cm['strong_sell']} strong sell")
            lm = r["live_market"]
            print(f"  Market state: {lm['market_state']} | regular: ${lm['regular_market_price']} "
                  f"| post-market: ${lm['post_market_price']} ({lm['post_market_change_pct']}%) "
                  f"| pre-market: ${lm['pre_market_price']} ({lm['pre_market_change_pct']}%)")
            headline_label = "company news" if r["headline_is_company_specific"] else "general market news (no company-specific story found)"
            print(f"  Latest headline [{headline_label}]: {r['latest_headline']} ({r['latest_headline_date']})")
