"""Run Stage 1 across the whole S&P 500 and report the tier distribution.

This is the number the page design depends on: a watchlist of 40 is a
different product from one of 250. Writes research/stage1_results.json so
Stage 2 and 3 work can start from a fixed list rather than re-querying
EDGAR every time.
"""
import json, pathlib, sys, time, collections

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from stage1_gates import load, run, decide, at_risk, S  # noqa: E402

HERE = pathlib.Path(__file__).parent
SCAN = HERE.parent / "output" / "latest_scan_sp500.json"

# Sector -> which Stage 1 track applies. Financials are judged on return
# on equity, because a bank's return on ASSETS is structurally ~1-1.5%.
FINANCIAL_SECTORS = {"Financial Services"}
SKIP_SECTORS = {"Real Estate"}   # REITs need an FFO-based track; not built


def main():
    scan = json.loads(SCAN.read_text())
    rows = {r["ticker"]: r for r in scan["all_results"]}
    m = S.get("https://www.sec.gov/files/company_tickers.json", timeout=30).json()
    cik = {v["ticker"].replace(".", "-"): str(v["cik_str"]).zfill(10) for v in m.values()}

    out, tiers = {}, collections.Counter()
    missing_cik, errors = [], []
    tickers = sorted(rows)
    for i, t in enumerate(tickers, 1):
        sector = rows[t].get("sector") or "Unknown"
        if sector in SKIP_SECTORS:
            tiers["REIT (not assessed)"] += 1
            out[t] = {"tier": "REIT (not assessed)", "sector": sector}
            continue
        if t not in cik:
            missing_cik.append(t)
            tiers["NO CIK"] += 1
            out[t] = {"tier": "NO CIK", "sector": sector}
            continue
        try:
            d = load(t, cik[t])
            gates = run(t, d, is_financial=sector in FINANCIAL_SECTORS)
            tier = decide(gates, t)
            out[t] = {
                "tier": tier, "sector": sector,
                "gates": [{"gate": n, "grade": g, "detail": dt} for n, g, dt in gates],
                "at_risk": at_risk(gates),
                "note": d.get("_note"),
            }
            tiers[tier] += 1
        except Exception as e:                      # noqa: BLE001
            errors.append((t, str(e)[:60]))
            tiers["ERROR"] += 1
            out[t] = {"tier": "ERROR", "sector": sector, "error": str(e)[:200]}
        if i % 50 == 0:
            print(f"   ...{i}/{len(tickers)}", flush=True)
        time.sleep(0.11)                            # SEC fair-use pacing

    (HERE / "stage1_results.json").write_text(json.dumps(out, indent=1))

    total = len(tickers)
    print(f"\n{'='*60}\nSTAGE 1 ACROSS THE FULL S&P 500  (n={total})\n{'='*60}")
    order = ["PASS", "BORDERLINE", "EXCEPTION", "REJECTED",
             "CANNOT ASSESS", "REIT (not assessed)", "NO CIK", "ERROR"]
    for k in order:
        if tiers.get(k):
            print(f"   {k:22s} {tiers[k]:4d}   {tiers[k]/total*100:5.1f}%")
    elig = tiers["PASS"] + tiers["BORDERLINE"] + tiers["EXCEPTION"]
    print(f"\n   -> {elig} companies ({elig/total*100:.0f}%) go through to Stages 2 and 3")

    print("\nWhich gate does the most rejecting?")
    gate_fail = collections.Counter()
    near_fail = collections.Counter()
    for t, r in out.items():
        for g in r.get("gates", []):
            if g["grade"] == "fail":
                gate_fail[g["gate"]] += 1
            elif g["grade"] == "near-fail":
                near_fail[g["gate"]] += 1
    for g in sorted(set(gate_fail) | set(near_fail)):
        print(f"   {g:24s} fail {gate_fail[g]:3d}   near-fail {near_fail[g]:3d}")

    print("\nTier by sector:")
    by_sec = collections.defaultdict(collections.Counter)
    for t, r in out.items():
        by_sec[r["sector"]][r["tier"]] += 1
    for sec in sorted(by_sec, key=lambda s: -sum(by_sec[s].values())):
        c = by_sec[sec]
        n = sum(c.values())
        p = c["PASS"] + c["BORDERLINE"] + c["EXCEPTION"]
        print(f"   {sec:24s} {p:3d}/{n:3d} eligible   "
              f"(pass {c['PASS']}, borderline {c['BORDERLINE']}, "
              f"rejected {c['REJECTED']}, n/a {c['CANNOT ASSESS']})")

    if errors:
        print(f"\nerrors ({len(errors)}): {errors[:8]}")
    if missing_cik:
        print(f"no CIK ({len(missing_cik)}): {missing_cik[:10]}")
    print("\nwrote research/stage1_results.json")


if __name__ == "__main__":
    main()
