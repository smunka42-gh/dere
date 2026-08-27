"""
Vantage — runs the full equity scan for every configured market and
saves each one to its own JSON file.

Output goes to output/<market.scan_output_file> — one file per market
(see markets.py) — the website reads from whichever file matches the
market currently selected in the UI, rather than re-scanning live on
every page load (that would be too slow — see DESIGN_DOC.md for the
batch-scan + live-refresh architecture).

Note this intentionally changes the S&P 500 output filename from the
older "latest_scan.json" to "latest_scan_sp500.json", so every market
follows the same naming convention. Anything still reading the old bare
filename (a currently-deployed build on a different branch, for example)
needs to be migrated deliberately when this feature merges — not papered
over here.
"""

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from markets import MARKETS
from recommendation_logic import evaluate_ticker

OUTPUT_DIR = Path(__file__).parent / "output"


def run_scan_for_market(market) -> None:
    tickers = market.fetch_tickers()
    print(f"\n=== {market.display_name} — scanning {len(tickers)} tickers ===")

    start_time = time.time()
    all_results = []
    errors = []

    for i, symbol in enumerate(tickers, start=1):
        try:
            result = evaluate_ticker(
                symbol,
                cap_tier_large=market.cap_tier_large,
                cap_tier_mid=market.cap_tier_mid,
                cap_tier_small=market.cap_tier_small,
            )
            if result is not None:
                all_results.append(result)
        except Exception as e:
            # One bad ticker (e.g. a delisted symbol, a temporary data
            # gap) shouldn't kill the whole scan — log it and move on.
            errors.append({"ticker": symbol, "error": str(e)})

        if i % 50 == 0:
            print(f"  ...{i}/{len(tickers)} done ({time.time() - start_time:.0f}s elapsed)")

    elapsed = time.time() - start_time
    recommendations = [r for r in all_results if r["recommended"]]

    scan_output = {
        "scan_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "market_id": market.id,
        "tickers_scanned": len(tickers),
        "tickers_with_errors": len(errors),
        "errors": errors,
        "total_recommendations": len(recommendations),
        "recommendations": recommendations,
        "all_results": all_results,  # includes non-recommendations too, useful for debugging
    }

    OUTPUT_DIR.mkdir(exist_ok=True)
    output_file = OUTPUT_DIR / market.scan_output_file
    with open(output_file, "w") as f:
        json.dump(scan_output, f, indent=2, default=str)

    print(f"Done in {elapsed:.0f}s ({elapsed / max(len(tickers), 1):.2f}s/ticker average)")
    print(f"Errors: {len(errors)} | Recommendations: {len(recommendations)}")
    for r in recommendations:
        print(f"  {r['ticker']}: [{r['tag']}] Composite Upside {r['composite_upside_pct']:+.1f}% "
              f"(100d-avg {r['upside_to_recent_avg_pct']:+.1f}%, 52w-high {r['upside_to_52w_high_pct']:+.1f}%, "
              f"target {r['upside_to_target_pct']:+.1f}%), rating {r['recommendation_mean']:.2f}")
    print(f"Saved to {output_file}")


def run_full_scan() -> None:
    for market in MARKETS.values():
        run_scan_for_market(market)


if __name__ == "__main__":
    run_full_scan()
