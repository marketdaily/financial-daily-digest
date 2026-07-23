#!/usr/bin/env python3
"""
ADR lead-lag: does 台積電 US ADR (TSM) overnight move predict 台積電 Taiwan (2330.TW)
the next Taiwan session — and how much is already eaten by the opening GAP?

HONEST measurement. Reuses the fetch/date-alignment basis of
quant_lab/crash_gate_night/fetch_global.py (Yahoo v8 daily OHLC, exchange-local
trading-date labels). Machine TZ is Asia/Taipei; dates are derived explicitly from
each bar's gmtoffset so the result is machine-TZ-independent.

Timezone alignment (the thing these analyses get wrong):
  - TW clock timeline over a normal Mon->Tue:
      Mon 09:00-13:30  2330 session (date=Mon)
      Mon 21:30-Tue04:00  TSM/US session (date=Mon)   <- happens AFTER 2330 Mon close
      Tue 09:00-13:30  2330 session (date=Tue)
  - So TSM's US-date-D overnight move is knowable at ~04:00 TW on D+1, BEFORE 2330's
    next session opens (09:00). It maps to 2330's *next TW trading day after D*.
  - Implementation aligns from the TW side (robust to holidays / many-to-one):
    for each 2330 session E, the driver is the LATEST TSM session D with D < E.

Dividend/split honesty: 2330 pays a large annual dividend; raw close-to-close would
show fake ex-div gaps. We use Yahoo adjclose to build an adjustment factor
(adj = adjclose/close) and apply it to open too (adjopen = open*adj). Gap and
close-to-close use adjusted prices. Note: OPEN-TO-CLOSE is invariant to the factor
(it cancels), so the key "tradeable intraday" number is robust to this choice.

No trading, no email. Measurement only.
"""
import urllib.request, urllib.parse, time, os, json, sys
import datetime as dt
import numpy as np

OUT = os.path.dirname(os.path.abspath(__file__))
SYMS = {"TSM": "tsm_o", "2330.TW": "tw2330_o"}   # *_o.json is gitignored in this dir
MIN_ROWS = 1000                                   # truncation guard (prior fake-num incident: 41 rows)


def fetch(sym, cache_name, force=False):
    """Yahoo v8 daily OHLC + adjclose. Returns list of dicts with exchange-local date.
    FAILS LOUD on a short/truncated pull."""
    path = os.path.join(OUT, f"{cache_name}.json")
    if os.path.exists(path) and not force:
        with open(path) as f:
            arr = json.load(f)
    else:
        url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}"
               f"?period1=631152000&period2={int(time.time())}&interval=1d&events=div%2Csplit")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        raw = json.loads(urllib.request.urlopen(req, timeout=45).read())
        res = raw["chart"]["result"][0]
        meta = res["meta"]
        goff = meta.get("gmtoffset", 0)
        ts = res["timestamp"]
        q = res["indicators"]["quote"][0]
        adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
        arr = []
        for i, t in enumerate(ts):
            o, c = q["open"][i], q["close"][i]
            a = adj[i] if adj else c
            if c is None or o is None or a is None:
                continue
            # exchange-local trading date (gmtoffset is current DST offset; bars are at
            # market-open ~mid-UTC-day, never near a UTC midnight, so the date is stable)
            d = (dt.datetime(1970, 1, 1) + dt.timedelta(seconds=t + goff)).date().isoformat()
            arr.append({"date": d, "open": o, "close": c, "adjclose": a})
        with open(path, "w") as f:
            json.dump(arr, f)
        print(f"  fetched {sym}: {len(arr)} rows ({arr[0]['date']} ~ {arr[-1]['date']})", flush=True)
        time.sleep(1.0)

    if len(arr) < MIN_ROWS:
        sys.exit(f"FATAL: {sym} returned only {len(arr)} rows (< {MIN_ROWS}). "
                 f"Refusing to compute stats on a truncated sample. Re-run (Yahoo rate-limit?).")
    return arr


def build(arr):
    """date -> (adjopen, adjclose). Applies adjfactor=adjclose/close to open."""
    out = {}
    dates = []
    for a in arr:
        d = dt.date.fromisoformat(a["date"])
        c, ac = a["close"], a["adjclose"]
        if c <= 0 or ac <= 0 or a["open"] <= 0:
            continue
        fac = ac / c
        out[d] = (a["open"] * fac, ac)   # (adjopen, adjclose)
        dates.append(d)
    return sorted(set(dates)), out


def ols(x, y):
    """Simple OLS y = a + b x. Returns dict with slope, intercept, r, r2, se_b, t_b, n."""
    x = np.asarray(x, float); y = np.asarray(y, float)
    n = len(x)
    b, a = np.polyfit(x, y, 1)
    yhat = a + b * x
    ss_res = float(np.sum((y - yhat) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    r = float(np.corrcoef(x, y)[0, 1])
    # slope std error
    sx = float(np.sum((x - x.mean()) ** 2))
    sigma2 = ss_res / (n - 2) if n > 2 else float("nan")
    se_b = (sigma2 / sx) ** 0.5 if sx > 0 else float("nan")
    t_b = b / se_b if se_b and se_b > 0 else float("nan")
    return {"b": b, "a": a, "r": r, "r2": r2, "se_b": se_b, "t": t_b, "n": n}


def main():
    force = "--refetch" in sys.argv
    print("Fetching (Yahoo v8 daily, adjusted)...")
    tsm_arr = fetch("TSM", "tsm_o", force)
    tw_arr = fetch("2330.TW", "tw2330_o", force)

    tsm_dates, tsm = build(tsm_arr)
    tw_dates, tw = build(tw_arr)

    # --- TSM overnight (US session D) = adjclose_D / adjclose_{prevTSMday} - 1 ---
    tsm_on = {}   # date -> overnight %
    for i in range(1, len(tsm_dates)):
        d, p = tsm_dates[i], tsm_dates[i - 1]
        tsm_on[d] = (tsm[d][1] / tsm[p][1] - 1) * 100

    # --- 2330 next-session pieces ---
    # gap = adjopen_E / adjclose_{prevTWday} - 1 ; cc = adjclose_E/adjclose_{prev} -1 ; oc = adjclose_E/adjopen_E -1
    gap, cc, oc = {}, {}, {}
    for i in range(1, len(tw_dates)):
        E, P = tw_dates[i], tw_dates[i - 1]
        o_e, c_e = tw[E]
        c_p = tw[P][1]
        gap[E] = (o_e / c_p - 1) * 100
        cc[E] = (c_e / c_p - 1) * 100
        oc[E] = (c_e / o_e - 1) * 100

    # --- ALIGN from TW side: for each 2330 session E, driver = latest TSM date D < E ---
    tsm_sorted = tsm_dates  # already sorted
    import bisect
    pairs = []   # (E, tsm_overnight, gap, cc, oc)
    for E in tw_dates:
        if E not in gap:
            continue
        j = bisect.bisect_left(tsm_sorted, E) - 1   # latest TSM date strictly < E
        if j < 0:
            continue
        D = tsm_sorted[j]
        if D not in tsm_on:
            continue
        pairs.append((E, tsm_on[D], gap[E], cc[E], oc[E]))

    if len(pairs) < MIN_ROWS:
        sys.exit(f"FATAL: only {len(pairs)} aligned pairs (< {MIN_ROWS}). Aborting (data problem).")

    Es = [p[0] for p in pairs]
    x = np.array([p[1] for p in pairs])   # TSM overnight
    g = np.array([p[2] for p in pairs])   # 2330 gap (open)
    c = np.array([p[3] for p in pairs])   # 2330 close-to-close
    ic = np.array([p[4] for p in pairs])  # 2330 open-to-close (intraday)
    n = len(pairs)
    years = (Es[-1] - Es[0]).days / 365.25

    print("\n" + "=" * 78)
    print(f"TSM (ADR)  ->  2330.TW   lead-lag   |   adjusted prices   |   HONEST measurement")
    print("=" * 78)
    print(f"Aligned pairs N = {n}   range {Es[0]} ~ {Es[-1]}   ({years:.1f} years)")
    print(f"TSM raw rows={len(tsm_arr)}  2330 raw rows={len(tw_arr)}  (both >> {MIN_ROWS}, no truncation)")
    print(f"Alignment: driver = latest TSM session strictly before each 2330 session (TW-side).")

    # base rates
    base_gap_up = float(np.mean(g > 0)) * 100
    base_oc_up = float(np.mean(ic > 0)) * 100
    print(f"\nBase rates: P(2330 gap up)={base_gap_up:.1f}%   P(2330 open->close up)={base_oc_up:.1f}%")
    print(f"Means: TSM overnight={x.mean():+.3f}%  2330 gap={g.mean():+.3f}%  "
          f"2330 c2c={c.mean():+.3f}%  2330 o2c(intraday)={ic.mean():+.3f}%")

    # ---------- (A) SAME-DIRECTION HIT RATE (TSM overnight vs 2330 open) ----------
    print("\n--- (A) SAME-DIRECTION HIT RATE: TSM overnight sign == 2330 OPEN(gap) sign ---")
    def hit_block(mask, label):
        m = mask & (x != 0)
        k = int(np.sum(m))
        if k < 20:
            print(f"  {label:34s} n={k:5d}   (too few)"); return
        same = float(np.mean(np.sign(x[m]) == np.sign(g[m]))) * 100
        up_up = float(np.mean(g[m & (x > 0)] > 0)) * 100 if np.sum(m & (x > 0)) else float('nan')
        dn_dn = float(np.mean(g[m & (x < 0)] < 0)) * 100 if np.sum(m & (x < 0)) else float('nan')
        print(f"  {label:34s} n={k:5d}   same-dir={same:5.1f}%   "
              f"P(gapUp|TSMup)={up_up:5.1f}%   P(gapDn|TSMdn)={dn_dn:5.1f}%")
    hit_block(np.ones(n, bool), "ALL")
    hit_block(np.abs(x) > 1, "|TSM overnight| > 1%")
    hit_block(np.abs(x) > 2, "|TSM overnight| > 2%")
    hit_block(np.abs(x) > 3, "|TSM overnight| > 3%")
    print(f"  (compare to base P(gap up)={base_gap_up:.1f}%)")

    # ---------- (B) GAP CAPTURE + intraday predictability ----------
    print("\n--- (B) GAP CAPTURE / decomposition (OLS: 2330 piece ~ a + b*TSM overnight) ---")
    rg, rc, ri = ols(x, g), ols(x, c), ols(x, ic)
    def line(tag, r):
        print(f"  2330 {tag:16s} ~ TSM :  beta={r['b']:+.3f}  r={r['r']:+.3f}  "
              f"R2={r['r2']:.3f}  t(beta)={r['t']:+6.1f}")
    line("GAP (open)", rg)
    line("close-to-close", rc)
    line("open-to-close", ri)
    print(f"  => decomposition check: beta_gap+beta_oc = {rg['b']+ri['b']:+.3f}  vs  beta_c2c = {rc['b']:+.3f}")
    if rc['b'] != 0:
        frac_gap = rg['b'] / rc['b'] * 100
        print(f"  => GAP CAPTURE: {frac_gap:.0f}% of TSM's total pass-through to 2330 is in the OPEN; "
              f"{100-frac_gap:.0f}% left for intraday.")
    print(f"  => TSM explains R2={rg['r2']:.3f} of 2330's OPEN gap, but only R2={ri['r2']:.4f} "
          f"of 2330's intraday (open->close).")

    # tradeability: conditional intraday mean vs costs
    print("\n  Intraday tradeability (2330 open->close mean, conditioned on TSM), TW day-trade cost ~0.2% RT:")
    for lab, m in [("TSM > +2%", x > 2), ("TSM > +1%", x > 1), ("TSM > 0", x > 0),
                   ("TSM < 0", x < 0), ("TSM < -1%", x < -1), ("TSM < -2%", x < -2)]:
        k = int(np.sum(m))
        if k < 20:
            print(f"    {lab:12s} n={k:5d}  (too few)"); continue
        mu = float(np.mean(ic[m])); md = float(np.median(ic[m]))
        pos = float(np.mean(ic[m] > 0)) * 100
        print(f"    {lab:12s} n={k:5d}  o->c mean={mu:+.3f}%  median={md:+.3f}%  P(up)={pos:4.1f}%")
    print(f"    (unconditional o->c mean={ic.mean():+.3f}%, P(up)={base_oc_up:.1f}%)")

    # ---------- (C) ERA STABILITY ----------
    print("\n--- (C) ERA STABILITY ---")
    eras = [(2000, 2010), (2011, 2017), (2015, 2020), (2018, 2020), (2021, 2026)]
    print(f"  {'era':11s} {'n':>5s}  {'same-dir':>8s}  {'beta_gap':>8s}  {'R2_gap':>7s}  "
          f"{'beta_oc':>8s}  {'R2_oc':>7s}  {'oc_mean':>8s}")
    for lo, hi in eras:
        idx = np.array([lo <= E.year <= hi for E in Es])
        k = int(np.sum(idx))
        if k < 50:
            print(f"  {lo}-{hi}  n={k:5d}  (too few)"); continue
        xe, ge, ice = x[idx], g[idx], ic[idx]
        same = float(np.mean(np.sign(xe[xe != 0]) == np.sign(ge[xe != 0]))) * 100
        re_g, re_i = ols(xe, ge), ols(xe, ice)
        print(f"  {lo}-{hi} {k:5d}  {same:7.1f}%  {re_g['b']:+8.3f}  {re_g['r2']:7.3f}  "
              f"{re_i['b']:+8.3f}  {re_i['r2']:7.4f}  {ice.mean():+7.3f}%")

    # ---------- (D) VERDICT ----------
    print("\n--- (D) HONEST VERDICT ---")
    same_all = float(np.mean(np.sign(x[x != 0]) == np.sign(g[x != 0]))) * 100
    frac_gap = rg['b'] / rc['b'] * 100 if rc['b'] else float('nan')
    dir_ok = same_all >= 65
    intraday_ok = (ri['r2'] > 0.02) and (abs(ri['b']) > 0.05)
    print(f"  (i) DIRECTION knowable for 'why' panel? "
          f"same-dir(open)={same_all:.0f}% vs base {base_gap_up:.0f}%, "
          f"gap R2={rg['r2']:.2f}, beta_gap={rg['b']:+.2f}. "
          f"=> {'YES, strong driver.' if dir_ok else 'weak.'}")
    print(f"  (ii) TRADEABLE intraday edge after 09:00 open? "
          f"open->close R2={ri['r2']:.4f}, beta_oc={ri['b']:+.3f}, "
          f"gap captures ~{frac_gap:.0f}% of pass-through. "
          f"=> {'possible' if intraday_ok else 'NO — essentially all in the gap; cannot chase after open.'}")
    print("=" * 78)


if __name__ == "__main__":
    main()
