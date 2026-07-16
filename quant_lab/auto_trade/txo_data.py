"""FinMind 免費層 → TXO 近月選擇權鏈日資料 → 每日 ATM IV + ±8% 履約價窗的 C/P 市價。

設計:賣方回測必須能「持有同一張合約幾天後用真實市價出場」,所以每天存的不是一個
IV 數字,而是 {contract, F(put-call parity 反推), atm_iv, dte, strikes:{K:{C,P}}}。
- 只取月合約(排除週選 'W')、日盤;近月=距結算 >= MIN_DTE 天,否則跳次月
- F 由 put-call parity(C-P+K)取雙邊有量履約價的中位數,不依賴期貨基差假設
- IV 用 Black-76(r=0 近似)bisection 反解 ATM call/put 平均
- 逐月抓、逐月縮減後入快取(.txo_iv.json),中斷可續跑
用法:python3 txo_data.py --start 2023-01-01
"""
import os
import json
import math
import time
import argparse
import datetime
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, ".txo_iv.json")
FINMIND = "https://api.finmindtrade.com/api/v4/data"
TOKEN = os.environ.get("FINMIND_TOKEN", "").strip()
MIN_DTE = 8          # 距結算 >= 8 天才算近月(留出場空間)
WIN = 0.08           # 存 |K-F|/F <= 8% 的履約價窗
MIN_VOL = 20         # parity/IV 用的最低成交量門檻


def third_wednesday(yyyymm):
    y, m = int(yyyymm[:4]), int(yyyymm[4:6])
    d = datetime.date(y, m, 1)
    offset = (2 - d.weekday()) % 7          # 週三=2
    return d + datetime.timedelta(days=offset + 14)


def fetch_month(y, m):
    start = f"{y}-{m:02d}-01"
    end = f"{y}-{m:02d}-{[31,29 if y%4==0 else 28,31,30,31,30,31,31,30,31,30,31][m-1]}"
    url = (f"{FINMIND}?dataset=TaiwanOptionDaily&data_id=TXO"
           f"&start_date={start}&end_date={end}")
    if TOKEN:
        url += f"&token={TOKEN}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read().decode()).get("data", [])


def bs76(F, K, T, vol, cp):
    if T <= 0 or vol <= 0:
        return max(F - K, 0.0) if cp == "c" else max(K - F, 0.0)
    d1 = (math.log(F / K) + 0.5 * vol * vol * T) / (vol * math.sqrt(T))
    d2 = d1 - vol * math.sqrt(T)
    N = lambda x: 0.5 * (1 + math.erf(x / math.sqrt(2)))
    if cp == "c":
        return F * N(d1) - K * N(d2)
    return K * N(-d2) - F * N(-d1)


def implied_vol(px, F, K, T, cp):
    intrinsic = max(F - K, 0.0) if cp == "c" else max(K - F, 0.0)
    if px <= intrinsic + 0.05:
        return None
    lo, hi = 0.01, 3.0
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if bs76(F, K, T, mid, cp) < px:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def reduce_day(rows_day, date):
    """一天的原始鏈 → 近月 {contract,F,atm_iv,dte,strikes}。資料不足回 None。"""
    d0 = datetime.date.fromisoformat(date)
    by_contract = {}
    for x in rows_day:
        cd = str(x.get("contract_date", ""))
        if "W" in cd or len(cd) != 6 or x.get("trading_session") not in (None, "position"):
            continue
        by_contract.setdefault(cd, []).append(x)
    pick = None
    for cd in sorted(by_contract):
        dte = (third_wednesday(cd) - d0).days
        if dte >= MIN_DTE:
            pick, dte_pick = cd, dte
            break
    if not pick:
        return None
    chain = {}
    for x in by_contract[pick]:
        K = x.get("strike_price")
        px = x.get("close") or 0
        v = x.get("volume") or 0
        if not K or px <= 0:
            continue
        side = "C" if x.get("call_put") == "call" else "P"
        chain.setdefault(K, {})[side] = {"px": px, "v": v}
    # put-call parity 反推 F
    fs = [K + c["C"]["px"] - c["P"]["px"] for K, c in chain.items()
          if "C" in c and "P" in c and c["C"]["v"] >= MIN_VOL and c["P"]["v"] >= MIN_VOL]
    if len(fs) < 3:
        return None
    fs.sort()
    F = fs[len(fs) // 2]
    T = dte_pick / 365.0
    K_atm = min(chain, key=lambda k: abs(k - F))
    ivs = []
    for side, cp in (("C", "c"), ("P", "p")):
        e = chain.get(K_atm, {}).get(side)
        if e and e["v"] >= MIN_VOL:
            iv = implied_vol(e["px"], F, K_atm, T, cp)
            if iv:
                ivs.append(iv)
    if not ivs:
        return None
    strikes = {str(K): {s: round(e["px"], 2) for s, e in c.items()}
               for K, c in chain.items() if abs(K - F) / F <= WIN}
    return {"contract": pick, "F": round(F, 1), "dte": dte_pick,
            "atm_K": K_atm, "atm_iv": round(sum(ivs) / len(ivs), 4), "strikes": strikes}


def load(start="2023-01-01", refresh=False):
    cache = {"start": start, "months": [], "days": {}}
    if not refresh and os.path.exists(CACHE):
        with open(CACHE, encoding="utf-8") as f:
            c = json.load(f)
        if c.get("start") == start:
            cache = c
    today = datetime.date.today()
    y, m = int(start[:4]), int(start[5:7])
    months = []
    while (y, m) <= (today.year, today.month):
        months.append((y, m))
        m += 1
        if m > 12:
            y, m = y + 1, 1
    for (yy, mm) in months:
        key = f"{yy}-{mm:02d}"
        if key in cache["months"] and (yy, mm) != (today.year, today.month):
            continue
        t0 = time.time()
        try:
            rows = fetch_month(yy, mm)
        except Exception as e:
            print(f"  {key} 抓取失敗:{e}(續跑可重試)")
            continue
        by_day = {}
        for x in rows:
            by_day.setdefault(x["date"], []).append(x)
        n = 0
        for d in sorted(by_day):
            r = reduce_day(by_day[d], d)
            if r:
                cache["days"][d] = r
                n += 1
        if key not in cache["months"]:
            cache["months"].append(key)
        with open(CACHE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False)
        print(f"  {key}:{len(rows):,} rows → {n} 天有效 ATM IV({time.time()-t0:.1f}s)")
    return cache["days"]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2023-01-01")
    ap.add_argument("--refresh", action="store_true")
    a = ap.parse_args()
    days = load(a.start, a.refresh)
    ds = sorted(days)
    print(f"\n共 {len(ds)} 天({ds[0]} → {ds[-1]})")
    for d in ds[-5:]:
        x = days[d]
        print(f"  {d} {x['contract']} F={x['F']:.0f} ATM_K={x['atm_K']:.0f} "
              f"IV={x['atm_iv']:.1%} dte={x['dte']} 窗內{len(x['strikes'])}檔")
