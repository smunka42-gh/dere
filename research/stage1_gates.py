"""Stage 1 quality gate — first real implementation, run as a regression test.

Reads audited figures straight from SEC EDGAR and applies the six gates
from the spec. Prints per-gate results so a pass or fail can be traced to
the number that caused it.
"""
import os
import requests, statistics as st, time

# The SEC REQUIRES callers to identify themselves with a contact address
# in the User-Agent, and silently returns non-JSON to requests without
# one. Read it from the environment rather than hard-coding it, so no
# personal contact detail is ever committed to this public repository.
#
#   export SEC_USER_AGENT="vantage-screener you@example.com"
#
# Failing loudly here is deliberate: the alternative is an opaque JSON
# decode error hundreds of lines later.
# Checked LAZILY, on first request — never at import time. Importing this
# module must not be able to kill the host process: Streamlit runs with
# runOnSave, which inspects .py files across the repo, so a module-level
# raise here took the deployed site down with an opaque ImportError.
class _SECSession(requests.Session):
    # An explicit flag, not a check on the header: requests.Session ships
    # a default User-Agent ("python-requests/x.y"), so testing whether one
    # is set always passes and the SEC silently rejects the call with
    # non-JSON hundreds of lines later.
    _ua_applied = False

    def request(self, method, url, *a, **kw):
        if not self._ua_applied:
            ua = os.environ.get("SEC_USER_AGENT")
            if not ua:
                raise RuntimeError(
                    "SEC_USER_AGENT is not set. The SEC requires a contact "
                    'address:  export SEC_USER_AGENT="vantage you@example.com"'
                )
            self.headers["User-Agent"] = ua
            self._ua_applied = True
        return super().request(method, url, *a, **kw)


S = _SECSession()

# Fallback chains: companies file the same economic fact under different
# concept names, so ask for any of them and take whichever exists.
CHAINS = {
    # "Operating income" is the concept we want, but banks, insurers,
    # conglomerates and much of pharma never present an operating-income
    # SUBTOTAL on their income statement, so they never tag it — a bank's
    # income statement has no meaningful "revenue minus operating costs"
    # line, because interest IS the business. They report pre-tax income
    # instead. Falling back to it is imperfect (it includes interest and
    # other non-operating items) but it is a far better answer than not
    # assessing JPMorgan, Berkshire, Lilly or J&J at all.
    "op_income": ["OperatingIncomeLoss",
                  "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
                  "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
                  "IncomeLossFromContinuingOperationsBeforeIncomeTaxesDomesticAndForeign"],
    "net_income": ["NetIncomeLoss", "ProfitLoss",
                   "NetIncomeLossAvailableToCommonStockholdersBasic"],
    "ocf": ["NetCashProvidedByUsedInOperatingActivities",
            "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment",
              "PaymentsToAcquireProductiveAssets",
              "PaymentsForCapitalImprovements"],
    "revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax",
                "Revenues", "RevenueFromContractWithCustomerIncludingAssessedTax",
                "SalesRevenueNet"],
    # Interest expense is the better solvency test but is thinly tagged
    # (27% single-tag, 54% chained), so it is PRIMARY where present and
    # equity/assets is the fallback. See gate 4.
    "interest": ["InterestExpense", "InterestExpenseDebt",
                 "InterestExpenseNonoperating", "InterestAndDebtExpense"],
}
INSTANT = {  # balance-sheet items: a point in time, not a period
    "assets": ["Assets"],
    "equity": ["StockholdersEquity",
               "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
}


def _pick(facts, tags, instant, min_recent_year=2023):
    """Latest annual value per fiscal year, for the first tag with RECENT data.

    Recency matters as much as length. Mastercard still carries a
    `NetIncomeLoss` series, but it stops in 2013 — modern years are filed
    under a different tag. Accepting the first chain entry with enough
    years would silently score the company on decade-old figures, so a
    series only qualifies if it also reaches the present.
    """
    best = {}
    for tag in tags:
        node = facts.get("us-gaap", {}).get(tag)
        if not node:
            continue
        units = node["units"].get("USD")
        if not units:
            continue
        by_year = {}
        for u in units:
            if u.get("form") != "10-K" or u.get("frame") is not None:
                continue
            if not instant and u.get("fp") != "FY":
                continue
            yr = u["end"][:4]
            # a year can be restated in a later filing; keep the newest
            if yr not in by_year or u["filed"] > by_year[yr]["filed"]:
                by_year[yr] = u
        if len(by_year) >= 4:
            series = {y: by_year[y]["val"] for y in by_year}
            if max(int(y) for y in series) >= min_recent_year:
                return series          # long enough AND current — take it
            best = best or series      # stale; keep only as a last resort
    return best


# Some filers split a figure across tags and never report the total.
# J&J, for instance, tags pre-tax income as Domestic and Foreign with 13
# years each, but the combined tag has only 4 — so the parts must be added.
SUM_PARTS = {
    "op_income": [["IncomeLossFromContinuingOperationsBeforeIncomeTaxesDomestic",
                   "IncomeLossFromContinuingOperationsBeforeIncomeTaxesForeign"]],
}


def _facts(cik):
    return S.get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json",
                 timeout=90).json()["facts"]


# Reorganised filers whose history sits under a predecessor CIK. EDGAR's
# ticker map returns the NEW entity, and its submissions record carries an
# empty formerNames list, so nothing links the two automatically. These are
# rare enough to name explicitly, and doing so is more honest than a fuzzy
# name search that could silently attach the wrong company's accounts.
PREDECESSOR_CIK = {
    "XOM": "0000034088",   # ExxonMobil Holdings Corp -> Exxon Mobil Corporation
}


def _resolve_cik(ticker, cik, facts):
    """Follow a reorganisation back to the predecessor that holds the history.

    EDGAR's ticker map returns the CURRENT filer. When a company
    reorganises, that entity is brand new: XOM maps to "ExxonMobil
    Holdings Corp" (94 tags, 0 annual years) while the real 19-year
    history sits under the predecessor CIK (438 tags). Without this, any
    restructured company silently loses its entire history.
    """
    ni = facts.get("us-gaap", {}).get("NetIncomeLoss")
    yrs = 0
    if ni:
        yrs = len({x["end"][:4] for x in ni["units"].get("USD", [])
                   if x.get("form") == "10-K" and x.get("fp") == "FY"})
    if yrs >= 4:
        return cik, facts, None
    alt = PREDECESSOR_CIK.get(ticker)
    if alt:
        return alt, _facts(alt), f"history read from predecessor CIK {alt}"
    return cik, facts, None


def load(ticker, cik):
    f = _facts(cik)
    cik, f, note = _resolve_cik(ticker, cik, f)
    d = {k: _pick(f, tags, False) for k, tags in CHAINS.items()}
    d.update({k: _pick(f, tags, True) for k, tags in INSTANT.items()})
    # Fill gaps by summing component tags where a filer reports only parts.
    for key, part_sets in SUM_PARTS.items():
        if len(d.get(key, {})) >= 4:
            continue
        for parts in part_sets:
            series = [_pick(f, [p], False) for p in parts]
            if all(len(s) >= 4 for s in series):
                yrs = set.intersection(*[set(s) for s in series])
                if len(yrs) >= 4:
                    d[key] = {y: sum(s[y] for s in series) for y in yrs}
                    break
    d["_note"] = note
    return d


def last5(series, years):
    return [series[y] for y in years if y in series]


# How close to a threshold still counts as "borderline", as a fraction of
# the bar itself. Proportional rather than absolute so it means the same
# thing whether the bar is 8% (returns) or 4x (interest coverage).
BORDERLINE = 0.15


def grade(value, bar, higher_is_better=True):
    """Classify a measurement against its threshold.

    Returns one of: pass · near-pass · near-fail · fail.

    A plain pass/fail hides how a company got there. A company clearing a
    bar by a hair is materially different from one clearing it by triple,
    and one missing by a hair is different from one missing by half — but
    boolean logic reports those pairs identically. The margin is the
    information, so it is kept rather than discarded.
    """
    if value is None or bar in (None, 0):
        return None, None
    slack = (value - bar) / abs(bar)
    if not higher_is_better:
        slack = -slack
    if slack >= BORDERLINE:
        return "pass", slack
    if slack >= 0:
        return "near-pass", slack
    if slack > -BORDERLINE:
        return "near-fail", slack
    return "fail", slack


def run(ticker, d, is_financial=False, is_utility=False,
        is_capital_intensive=False, shock_years=()):
    """Apply the six gates. Returns list of (gate, passed|None, detail)."""
    # Year spine: built from whichever profit series exists, so a thin
    # tag in ONE concept cannot blank out gates that don't depend on it.
    # (Mastercard's stale NetIncomeLoss previously emptied this list and
    # took two unrelated gates down with it.)
    profit_years = set(d["op_income"]) | set(d["net_income"])
    yrs = sorted(profit_years & set(d["assets"]))[-5:]
    out = []

    # --- Test 1: sustained profitability -----------------------------
    # Financials get the same one-bad-year allowance on the profit series
    # that everyone gets on net income. Insurers must mark their
    # investment portfolio to market, so Berkshire's 2022 pre-tax figure
    # was -$30.5B purely from unrealised equity revaluation while its
    # operating businesses were fine. Penalising that is measuring the
    # stock market, not the company.
    # Years the WHOLE sector lost money are excluded before counting. A
    # year in which most of an industry's largest companies posted an
    # operating loss is an exogenous shock, not evidence about any one
    # company: in 2020, 5 of the 7 largest energy names went negative,
    # against 0% in every other year. Excusing that year is mechanical
    # (it identifies an industry-wide event) rather than a lowered bar —
    # a company that also lost money OUTSIDE the shock year still fails.
    judged = [y for y in yrs if y not in shock_years]
    oi = last5(d["op_income"], judged)
    ni = last5(d["net_income"], judged)
    # Banks, insurers and asset managers frequently have NO usable
    # operating-income series at all — Allstate tags none, and Aflac's
    # stops in 2021 — because the concept is not meaningful for them.
    # Requiring it made 8 established financials "cannot assess" purely
    # on a missing tag. For those, net income IS the profit measure, and
    # it has excellent coverage; gate 2 already judges them on ROE, which
    # is built from the same figure.
    if is_financial and len(oi) < 4 and len(ni) >= 4:
        oi = ni
    if len(oi) >= 4 and len(ni) >= 4:
        neg_allowed = 1 if is_financial else 0
        oi_neg = sum(1 for x in oi if x <= 0)
        ok = oi_neg <= neg_allowed and sum(1 for x in ni if x > 0) >= len(ni) - 1
        out.append(("1 Sustained profit", "pass" if ok else "fail",
                    f"profit negative {oi_neg}/{len(oi)}y (allowed {neg_allowed})"
                    f"{' [shock yrs excluded: '+','.join(sorted(shock_years))+']' if shock_years else ''} · "
                    f"net income positive {sum(1 for x in ni if x>0)}/{len(ni)}"))
    else:
        out.append(("1 Sustained profit", None, "insufficient history"))

    # --- Test 2: returns on capital (level OR improving) -------------
    # SECTOR RULE, and the only one the evidence forced. Banks and
    # insurers hold enormous balance sheets against thin spreads, so
    # return on ASSETS is structurally ~1-1.5% for a perfectly healthy
    # bank: JPMorgan runs 1.0-1.5% ROA while earning 12.9-17.0% ROE. An
    # 8% ROA bar is not strict for a bank, it is impossible. Financials
    # are therefore judged on return on EQUITY, the yardstick the
    # industry itself uses.
    if is_financial or is_utility or is_capital_intensive:
        vals = [d["net_income"][y] / d["equity"][y] for y in yrs
                if y in d["net_income"] and d["equity"].get(y)]
        # Utilities: 8% anchors to the ALLOWED ROE regulators grant, which
        # runs 9-10.5% in the US. A utility earning well under its own
        # allowance (Duke at 5.8%) is genuinely underperforming, not merely
        # capital-intensive — so the bar still discriminates.
        if is_utility:
            bar, near, label = 0.08, 0.07, "return on equity"
        else:
            # Financials and capital-intensive competitive businesses
            # (telecom, cable, media) share a 10% bar. Unlike a regulated
            # utility they carry competitive risk and have no allowed
            # return to anchor to, so they should out-earn one.
            bar, near, label = 0.10, 0.09, "return on equity"
    else:
        vals = [d["op_income"][y] * 0.79 / d["assets"][y] for y in yrs
                if y in d["op_income"] and d["assets"].get(y)]
        bar, near, label = 0.08, 0.07, "return on assets"
    if len(vals) >= 4:
        med, latest = st.median(vals), vals[-1]
        improving = latest >= near and latest > med
        g, slack = grade(med, bar)
        if improving and g in ("near-fail", "fail"):
            g, slack = "pass", 0.0          # improvement clause overrides level
            why = "improving"
        else:
            why = "level"
        out.append(("2 Return on capital", g,
                    f"{label} median {med*100:.1f}% vs {bar*100:.0f}% bar · "
                    f"latest {latest*100:.1f}% ({why})"))
    else:
        out.append(("2 Return on capital", None, "insufficient history"))

    # --- Test 3: cumulative free cash flow ---------------------------
    # Utilities are judged on OPERATING cash flow instead. Free cash flow
    # is negative by design for a regulated utility: it continuously funds
    # grid capex with debt against regulator-guaranteed returns, so 26 of
    # 31 showed negative cumulative 5y FCF. What matters is whether the
    # business throws off cash before that investment, every year.
    if is_utility and d["ocf"]:
        cy = sorted(d["ocf"])[-5:]
        vals = [d["ocf"][y] for y in cy]
        out.append(("3 Cumulative 5y FCF", "pass" if min(vals) > 0 else "fail",
                    f"operating cash flow positive {sum(1 for v in vals if v>0)}/{len(vals)}y "
                    f"(utility track: capex excluded)"))
    elif d["ocf"] and d["capex"]:
        cy = sorted(set(d["ocf"]) & set(d["capex"]))[-5:]
        fcf = sum(d["ocf"][y] - d["capex"][y] for y in cy)
        out.append(("3 Cumulative 5y FCF", "pass" if fcf > 0 else "fail",
                    f"${fcf/1e9:+.1f}B over {len(cy)}y"))
    elif d["ocf"]:
        cy = sorted(d["ocf"])[-5:]
        tot = sum(d["ocf"][y] for y in cy)
        out.append(("3 Cumulative 5y FCF", "pass" if tot > 0 else "fail",
                    f"${tot/1e9:+.1f}B operating cash (no capex tag)"))
    else:
        out.append(("3 Cumulative 5y FCF", None, "no cash-flow tag"))

    # --- Test 4: can the debt be serviced? ---------------------------
    # Coverage asks the real question ("can it pay the interest?") and is
    # tried FIRST. Equity/assets is only the fallback, because on its own
    # it fails Apple (15.6%) and GE (16.2%) for buybacks and restructuring
    # rather than for any quality problem — leverage is not a defect if
    # the earnings comfortably service it.
    y = yrs[-1] if yrs else None
    ie = d["interest"].get(y) if y else None
    if y and ie and d["op_income"].get(y):
        cov = d["op_income"][y] / abs(ie)
        # Regulated utilities carry more debt against far more predictable
        # cash flows, so 2.5x there is the equivalent of 4x elsewhere.
        cov_bar = 2.5 if is_utility else 4.0
        g, _ = grade(cov, cov_bar)
        out.append(("4 Debt serviceable", g,
                    f"interest coverage {cov:.1f}x vs {cov_bar}x bar"))
    elif y and d["equity"].get(y) and d["assets"].get(y):
        ratio = d["equity"][y] / d["assets"][y]
        # Deliberately loose: this is a crude proxy used ONLY when the
        # real test is unavailable, so it should catch the obviously
        # over-levered without second-guessing companies it cannot
        # properly measure. At 15% Apple cleared by 0.6 points, which is
        # luck rather than judgement.
        bar = 0.08 if is_financial else 0.10
        g, _ = grade(ratio, bar)
        out.append(("4 Debt serviceable", g,
                    f"equity/assets {ratio*100:.1f}% vs {bar*100:.0f}% bar (no interest tag)"))
    else:
        out.append(("4 Debt serviceable", None, "no interest or equity tag"))

    # --- Test 5: operating margin not deteriorating ------------------
    # RELATIVE, not absolute. An absolute band cannot serve both ends of
    # the margin range: 6 percentage points is a rounding error to a 40%-
    # margin semiconductor firm and a catastrophe to a 5%-margin retailer.
    # Dollar General's margin roughly HALVED (8.2% -> 4.2%) and still
    # passed a 6pp band. Requiring the latest to hold 70% of the 3-year
    # average fails DG at 51% while passing TXN at 74%.
    om = [d["op_income"][y] / d["revenue"][y] for y in yrs
          if y in d["op_income"] and d["revenue"].get(y)]
    if len(om) >= 4:
        ref = st.mean(om[-4:-1])
        ratio = (om[-1] / ref) if ref > 0 else 0.0
        g, _ = grade(ratio, 0.70)
        out.append(("5 Op margin durable", g,
                    f"latest {om[-1]*100:.1f}% is {ratio*100:.0f}% of 3y avg "
                    f"{ref*100:.1f}% (70% bar)"))
    else:
        out.append(("5 Op margin durable", None, "no revenue tag match"))

    # --- Test 6: liquidity (price data, checked separately) ----------
    out.append(("6 Liquidity", "pass", "all S&P 500 clear $25M/day"))
    return out


# ---------------------------------------------------------------------
# EXCEPTIONS — deliberate, named, auditable overrides.
#
# The point of these is to STOP THRESHOLDS DRIFTING. Without an exception
# mechanism, the only way to admit one company you believe in is to lower
# a bar — which silently changes the answer for all 500 and quietly
# overfits the thresholds to whichever names happen to be in the golden
# set. An exception changes the answer for exactly one company, states
# why in writing, and expires.
#
# Two hard rules keep this from becoming a backdoor:
#   1. An exception can only rescue a NEAR-FAIL, never an outright fail.
#      If a company misses a bar badly, no override applies.
#   2. It must name the specific gate. A blanket "let this company in"
#      is not permitted.
#
# Every exception carries a review date and is displayed in the UI as
# "on watchlist by exception", never as a clean pass.
EXCEPTIONS = {
    # "JNJ": {"gate": "2", "reason": "...", "granted": "2026-08-29",
    #          "review_by": "2027-02-01"},
}


def decide(gates, ticker=None):
    """Resolve six graded gates into a watchlist tier.

      PASS           every gate cleared (a near-pass IS a pass)
      BORDERLINE     exactly one near-fail, nothing worse
      EXCEPTION      a near-fail deliberately overridden — see EXCEPTIONS
      REJECTED       any outright fail, or two or more near-fails
      CANNOT ASSESS  fewer than 4 of 5 substantive gates evaluable

    PASS, BORDERLINE and EXCEPTION are all ELIGIBLE for Stages 2 and 3 —
    the tier travels with the company rather than being collapsed away, so
    the UI can always show whether a name is on the list cleanly, barely,
    or by override. That keeps the thresholds fixed: a near-miss is
    recorded as a near-miss instead of prompting someone to move the bar.
    """
    substantive = gates[:5]
    grades = [(n, g) for n, g, _ in substantive if g is not None]
    if len(grades) < 4:
        return "CANNOT ASSESS"
    if any(g == "fail" for _, g in grades):
        return "REJECTED"
    near = [n for n, g in grades if g == "near-fail"]
    if not near:
        return "PASS"
    if len(near) > 1:
        return "REJECTED"
    exc = EXCEPTIONS.get(ticker)
    if exc and near[0].split()[0] == str(exc["gate"]):
        return "EXCEPTION"
    return "BORDERLINE"


ELIGIBLE = {"PASS", "BORDERLINE", "EXCEPTION"}


def eligible(verdict):
    """Does this company go through to Stages 2 and 3?"""
    return verdict in ELIGIBLE


def at_risk(gates):
    """Gates a watchlist member is closest to failing — Stage 3 input."""
    return [n for n, g, _ in gates if g == "near-pass"]


if __name__ == "__main__":
    m = S.get("https://www.sec.gov/files/company_tickers.json", timeout=30).json()
    CIK = {v["ticker"].replace(".", "-"): str(v["cik_str"]).zfill(10) for v in m.values()}

    # GOLDEN SET — cases where the right answer is known independently of
    # this code. Positives are the user's high-conviction compounders plus
    # the names the S&P 500 Quality Index also selects. Negatives are
    # widely-recognised quality-deterioration cases. Debatable names
    # (TXN, CSCO, GE, ORCL, CVS, DG, EL) are deliberately EXCLUDED: a
    # golden set may only contain cases we are certain about.
    EXPECTED = {
        "AMZN": True, "META": True, "AAPL": True, "NVDA": True, "NFLX": True,
        "GOOG": True, "BRK-B": True, "COST": True, "WMT": True, "MA": True,
        "V": True, "ISRG": True, "MSFT": True,
        "INTC": False, "BA": False, "F": False, "MMM": False,
    }
    FINANCIALS = {"BRK-B", "V", "MA"}

    results, verdict = {}, {}
    for t in EXPECTED:
        results[t] = run(t, load(t, CIK[t]), is_financial=t in FINANCIALS)
        verdict[t] = eligible(decide(results[t], t))
        time.sleep(0.2)

    def block(title, names):
        print(f"\n{title}")
        print(f"  {'tkr':7s} {'got':>6s} {'want':>6s}  {'':2s} failing gates")
        print("  " + "-" * 62)
        for t in names:
            agree = verdict[t] == EXPECTED[t]
            bad = ", ".join(f"{n.split()[0]}{'~' if o=='near-fail' else ''}"
                            for n, o, _ in results[t] if o in ("fail","near-fail"))
            print(f"  {t:7s} {('PASS' if verdict[t] else 'FAIL'):>6s} "
                  f"{('PASS' if EXPECTED[t] else 'FAIL'):>6s}  {'ok' if agree else '<<':2s} {bad or '—'}")

    block("POSITIVES — must pass", [t for t in EXPECTED if EXPECTED[t]])
    block("NEGATIVES — must fail", [t for t in EXPECTED if not EXPECTED[t]])

    wrong = [t for t in EXPECTED if verdict[t] != EXPECTED[t]]
    print("\n" + "=" * 66)
    if wrong:
        print(f"REGRESSION TEST: FAIL — {len(wrong)} anchor(s) moved: {', '.join(wrong)}")
        for t in wrong:
            print(f"\n  {t} detail:")
            for name, o, detail in results[t]:
                print(f"     {(o or 'n/a'):>10s}  {name:22s} {detail}")
    else:
        print(f"REGRESSION TEST: PASS — all {len(EXPECTED)} anchors behaved as specified")
