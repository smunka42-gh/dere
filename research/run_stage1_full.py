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
UTILITY_SECTORS = {"Utilities"}
# Capital-intensive but COMPETITIVE (not rate-regulated): telecom, cable,
# media. Asset-heavy like utilities, so return on assets misreads them —
# but unlike utilities they generate strong free cash flow (VZ +$64B,
# T +$111B, CMCSA +$83B cumulative 5y), so only gate 2 changes.
CAPITAL_INTENSIVE_SECTORS = {"Communication Services"}

# Managed-care insurers that the data provider files under "Healthcare".
# They are insurance companies: premiums in, claims out, large investment
# float — so return on ASSETS misreads them exactly as it does a bank.
# Named explicitly rather than matched on company name, which wrongly
# swept in hospitals (HCA, UHS), a distributor (CAH) and a device maker
# (GEHC). CVS is included deliberately: post-Aetna its balance sheet is
# insurance-dominated, though it remains part retail.
HEALTH_INSURERS = {"UNH", "ELV", "CI", "HUM", "CNC", "MOH", "CVS"}
SKIP_SECTORS = {"Real Estate"}   # REITs need an FFO-based track; not built


def main():
    scan = json.loads(SCAN.read_text())
    rows = {r["ticker"]: r for r in scan["all_results"]}
    m = S.get("https://www.sec.gov/files/company_tickers.json", timeout=30).json()
    cik = {v["ticker"].replace(".", "-"): str(v["cik_str"]).zfill(10) for v in m.values()}

    out, tiers = {}, collections.Counter()
    missing_cik, errors = [], []
    tickers = sorted(rows)

    # --- Pass 1: load every company once, and find sector shock years ---
    # A year where most of a sector's LARGEST companies posted an
    # operating loss is an industry-wide event, not a company signal.
    print("loading filings...", flush=True)
    data = {}
    for i, t in enumerate(tickers, 1):
        if rows[t].get("sector") in SKIP_SECTORS or t not in cik:
            continue
        try:
            data[t] = load(t, cik[t])
        except Exception as e:                      # noqa: BLE001
            errors.append((t, str(e)[:60]))
        if i % 100 == 0:
            print(f"   ...{i}/{len(tickers)}", flush=True)
        time.sleep(0.11)

    SHOCK_SHARE = 0.50        # >=50% of the sector's big names negative
    SHOCK_TOP_N = 10          # judged on the 10 largest by market cap
    shock = collections.defaultdict(set)
    by_sector = collections.defaultdict(list)
    for t, d in data.items():
        by_sector[rows[t].get("sector") or "Unknown"].append(t)
    for sec, names in by_sector.items():
        biggest = sorted(names, key=lambda x: -(rows[x].get("market_cap") or 0))[:SHOCK_TOP_N]
        year_neg, year_n = collections.Counter(), collections.Counter()
        for t in biggest:
            oi = data[t]["op_income"]
            # SAME 5-year window the gates judge on. Detecting a shock
            # over a longer span than the gates use would let a year be
            # excused that was never going to be counted anyway, and
            # would make the two definitions silently disagree.
            for y in sorted(oi)[-5:]:
                year_n[y] += 1
                if oi[y] <= 0:
                    year_neg[y] += 1
        for y, n in year_n.items():
            if n >= 4 and year_neg[y] / n >= SHOCK_SHARE:
                shock[sec].add(y)
    if shock:
        print("\nsector-wide shock years detected:")
        for sec, ys in sorted(shock.items()):
            print(f"   {sec:24s} {', '.join(sorted(ys))}")
    print()
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
        d = data.get(t)
        if d is None:
            tiers["ERROR"] += 1
            out[t] = {"tier": "ERROR", "sector": sector}
            continue
        try:
            gates = run(t, d, is_financial=(sector in FINANCIAL_SECTORS
                                        or t in HEALTH_INSURERS),
                        is_utility=sector in UTILITY_SECTORS,
                        is_capital_intensive=sector in CAPITAL_INTENSIVE_SECTORS,
                        shock_years=shock.get(sector, set()))
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
