"""
DERE — runs the full S&P 500 scan and saves results to a JSON file.

This is the script that would eventually run on a schedule (~6am
Central, per the design doc) — right now we're running it manually to
validate at full scale before setting up any scheduling.

Output goes to output/latest_scan.json — the website will read from
this file rather than re-scanning all 500 tickers on every page load
(that would be too slow — see DESIGN_DOC.md for the batch-scan +
live-refresh-for-flagged-tickers architecture).
"""

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from sp500_tickers import get_sp500_tickers
from recommendation_logic import evaluate_ticker

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_FILE = OUTPUT_DIR / "latest_scan.json"


def run_full_scan():
    tickers = get_sp500_tickers()
    print(f"Scanning {len(tickers)} tickers...")

    start_time = time.time()
    all_results = []
    errors = []

    for i, symbol in enumerate(tickers, start=1):
        try:
            result = evaluate_ticker(symbol)
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
        "tickers_scanned": len(tickers),
        "tickers_with_errors": len(errors),
        "errors": errors,
        "total_recommendations": len(recommendations),
        "recommendations": recommendations,
        "all_results": all_results,  # includes non-recommendations too, useful for debugging
    }

    OUTPUT_DIR.mkdir(exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(scan_output, f, indent=2, default=str)

    print(f"\nDone in {elapsed:.0f}s ({elapsed/len(tickers):.2f}s/ticker average)")
    print(f"Errors: {len(errors)}")
    print(f"Recommendations: {len(recommendations)}")
    for r in recommendations:
        print(f"  {r['ticker']}: [{r['tag']}] Composite Upside {r['composite_upside_pct']:+.1f}% "
              f"(100d-avg {r['upside_to_recent_avg_pct']:+.1f}%, 52w-high {r['upside_to_52w_high_pct']:+.1f}%, "
              f"target {r['upside_to_target_pct']:+.1f}%), rating {r['recommendation_mean']:.2f}")
    print(f"\nSaved to {OUTPUT_FILE}")


if __name__ == "__main__":
    run_full_scan()
