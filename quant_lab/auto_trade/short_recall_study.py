"""台股融券強制回補 squeeze 研究(魚池 Tier B):除權息停止過戶前融券戶被法規強制回補
=結構性輸家買盤。假說:回補壓力大(days-to-cover 高)的股票在最後回補日前有超額正報酬。

設計(誠實口徑):
- 事件=每檔每次除權息(TaiwanStockDividendResult.date=除權息日 T0)。
- 最後回補日 D ≈ T0 往前第 6 個交易日(法規近似,寫死為假設 RECALL_OFFSET=6)。
- 訊號日 S = D−15 交易日:回補壓力 dtc = 融券餘額(張) ÷ 近20日均量(張)。無前視:
  進場最早在 D−10,晚於訊號日 5 天。
- 報酬窗 [D−10,D] 主、[D−5,D] 次,皆收盤→收盤且在 T0 前結束(不跨除權息,免還原價;
  仍檢查窗內無該股其他除權息日)。
- 高壓組=同年度事件橫斷面 dtc 前 10%/20%(限餘額>0);placebo=融券餘額≈0(≤10張)的
  同期除權息事件;自身對照=同股票 D−40 結尾的同長度窗(避開任何除權息 ±12 交易日)。
- t 值一律以「事件 ISO 週」cluster 聚合(除權息集中 6-8 月,同週高度相關,逐筆當獨立會虛胖)。
- 成本 0.45%(證交稅0.3%+雙邊手續費0.1%+滑價)。
- Universe:FinMind 免費層無橫斷面查詢(400 Your level is register),縮為 TWSE 上市普通股
  「2021-2025 各取一天快照之平均成交金額前 150 大」(≈台灣50+中型100;上櫃缺席、且以
  近年流動性選樣有輕微存活者偏差,誠實記錄)。
用法:python3 short_recall_study.py  (資料快取 .short_recall/,中斷可續跑)
"""
import os
import json
import math
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, ".short_recall")
FINMIND = "https://api.finmindtrade.com/api/v4/data"
COST = 0.0045
RECALL_OFFSET = 6      # D = 除權息日往前第 6 個交易日(假設)
SIGNAL_OFFSET = 15     # 訊號日 = D-15
UNIVERSE_N = 150
SNAP_DATES = ["20210414", "20220413", "20230412", "20240410", "20250409"]
REQ = {"finmind": 0}


def _token():
    t = os.environ.get("FINMIND_TOKEN", "").strip()
    if t:
        return t
    for p in (os.path.join(HERE, "../../.env"), os.path.join(HERE, "../../cb_analyzer/.env")):
        try:
            for line in open(p):
                if line.startswith("FINMIND_TOKEN"):
                    return line.split("=", 1)[1].strip()
        except OSError:
            pass
    return ""


TOKEN = _token()


def _get(url, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read().decode())
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(3 * (i + 1))


def finmind(dataset, data_id, start, end="2025-12-31"):
    fn = os.path.join(CACHE, f"{dataset}_{data_id}.json")
    if os.path.exists(fn):
        return json.load(open(fn))
    url = (f"{FINMIND}?dataset={dataset}&data_id={data_id}"
           f"&start_date={start}&end_date={end}&token={TOKEN}")
    d = _get(url)
    if d.get("status") != 200:
        if "600 requests" in str(d.get("msg", "")):
            print("  限流,睡 10 分鐘…")
            time.sleep(600)
            d = _get(url)
        if d.get("status") != 200:
            raise RuntimeError(f"FinMind {dataset} {data_id}: {d.get('msg')}")
    REQ["finmind"] += 1
    time.sleep(0.15)
    rows = d.get("data", [])
    json.dump(rows, open(fn, "w"))
    return rows


def universe():
    fn = os.path.join(CACHE, "universe.json")
    if os.path.exists(fn):
        return json.load(open(fn))
    val = {}
    for dt in SNAP_DATES:
        d = _get(f"https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
                 f"?date={dt}&type=ALLBUT0999&response=json")
        for t in d.get("tables", []):
            if "證券代號" in t.get("fields", []):
                for row in t["data"]:
                    sid = row[0].strip()
                    if len(sid) == 4 and sid.isdigit() and not sid.startswith("0"):
                        val.setdefault(sid, []).append(float(row[4].replace(",", "")))
        time.sleep(1)
    ranked = sorted((s for s, v in val.items() if len(v) >= 4),
                    key=lambda s: -sum(val[s]) / len(val[s]))
    top = ranked[:UNIVERSE_N]
    json.dump(top, open(fn, "w"))
    return top


def load_stock(sid):
    px = finmind("TaiwanStockPrice", sid, "2020-10-01")
    ss = finmind("TaiwanStockMarginPurchaseShortSale", sid, "2020-10-01")
    dv = finmind("TaiwanStockDividendResult", sid, "2021-01-01")
    prices = {r["date"]: (r["close"], r["Trading_Volume"]) for r in px if r["close"] > 0}
    shorts = {r["date"]: r["ShortSaleTodayBalance"] for r in ss}
    exdates = sorted({r["date"] for r in dv if "2021-01-01" <= r["date"] <= "2025-12-31"})
    return prices, shorts, exdates


def week_key(date):
    import datetime
    y, w, _ = datetime.date(*map(int, date.split("-"))).isocalendar()
    return f"{y}-W{w:02d}"


def cluster_t(pairs):
    """pairs=[(week,ret)] → 以週 cluster 聚合後的 (mean, t, n_events, n_clusters)。"""
    if not pairs:
        return None
    by = {}
    for w, r in pairs:
        by.setdefault(w, []).append(r)
    cm = [sum(v) / len(v) for v in by.values()]
    n = len(cm)
    mean_ev = sum(r for _, r in pairs) / len(pairs)
    if n < 3:
        return mean_ev, 0.0, len(pairs), n
    m = sum(cm) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in cm) / (n - 1))
    t = m / (sd / math.sqrt(n)) if sd > 0 else 0.0
    return mean_ev, t, len(pairs), n


def build_events(top):
    cal_px, _, _ = load_stock("2330")
    cal = sorted(cal_px)                      # 市場交易日曆(2330 全勤)
    cidx = {d: i for i, d in enumerate(cal)}
    events = []
    for sid in top:
        try:
            prices, shorts, exdates = load_stock(sid)
        except RuntimeError as e:
            print(f"  跳過 {sid}: {e}")
            continue
        for ex in exdates:
            if ex not in cidx:
                continue
            i0 = cidx[ex]
            iD = i0 - RECALL_OFFSET
            iS = iD - SIGNAL_OFFSET
            if iS - 20 < 0:
                continue
            D, S = cal[iD], cal[iS]
            # 訊號:S 日融券餘額(允許回看 3 個交易日)÷ S 前 20 日均量(張)
            bal = next((shorts[cal[iS - k]] for k in range(4) if cal[iS - k] in shorts), None)
            vols = [prices[cal[j]][1] / 1000 for j in range(iS - 19, iS + 1) if cal[j] in prices]
            if bal is None or len(vols) < 15:
                continue
            adv20 = sum(vols) / len(vols)
            if adv20 <= 0:
                continue
            dtc = bal / adv20
            # 報酬窗(不得含該股其他除權息日)
            def wret(i_in, i_out):
                d_in, d_out = cal[i_in], cal[i_out]
                if d_in not in prices or d_out not in prices:
                    return None
                if any(d_in < e <= d_out for e in exdates):
                    return None
                return prices[d_out][0] / prices[d_in][0] - 1
            r10, r5 = wret(iD - 10, iD), wret(iD - 5, iD)
            # 自身對照:同長度窗,結尾在 D-40,且避開任何除權息 ±12 交易日
            iC = iD - 40
            ctl10 = ctl5 = None
            if iC - 10 >= 0:
                near = any(abs(cidx[e] - iC) <= 12 for e in exdates if e in cidx)
                if not near:
                    ctl10, ctl5 = wret(iC - 10, iC), wret(iC - 5, iC)
            if r10 is None and r5 is None:
                continue
            events.append({"sid": sid, "ex": ex, "D": D, "S": S, "year": ex[:4],
                           "bal": bal, "dtc": dtc, "r10": r10, "r5": r5,
                           "ctl10": ctl10, "ctl5": ctl5, "week": week_key(D)})
    return events


def pct_cut(vals, q):
    v = sorted(vals)
    return v[min(len(v) - 1, int(len(v) * q))]


def classify(events, top_q):
    """同年度橫斷面:dtc≥(1-top_q)分位且餘額>0 → 高壓;餘額≤10張 → placebo。"""
    hi, pl = set(), set()
    by_year = {}
    for i, e in enumerate(events):
        by_year.setdefault(e["year"], []).append(i)
    for _, idxs in by_year.items():
        pos = [events[i]["dtc"] for i in idxs if events[i]["bal"] > 0]
        if len(pos) < 10:
            continue
        cut = pct_cut(pos, 1 - top_q)
        for i in idxs:
            if events[i]["bal"] > 0 and events[i]["dtc"] >= cut:
                hi.add(i)
            elif events[i]["bal"] <= 10:
                pl.add(i)
    return hi, pl


def fmt(tag, st, cost=None):
    if not st:
        print(f"  {tag:<34} 樣本不足")
        return
    m, t, n, nc = st
    net = f"  淨(扣0.45%) {m - COST:+.2%}" if cost else ""
    print(f"  {tag:<34} n={n:>4} 週clust={nc:>3}  均 {m:+.2%}  t={t:+.2f}{net}")


def report(events, top_q, rkey, ckey):
    hi, pl = classify(events, top_q)
    H = [events[i] for i in hi if events[i][rkey] is not None]
    P = [events[i] for i in pl if events[i][rkey] is not None]
    label = f"top{int(top_q*100)}% × {rkey}"
    print(f"\n── 變體 {label} ──")
    st_h = cluster_t([(e["week"], e[rkey]) for e in H])
    st_p = cluster_t([(e["week"], e[rkey]) for e in P])
    fmt("高壓組(毛)", st_h, cost=True)
    fmt("placebo 零融券組(毛)", st_p)
    # 高壓 − placebo:同週皆有才比
    bw_h, bw_p = {}, {}
    for e in H:
        bw_h.setdefault(e["week"], []).append(e[rkey])
    for e in P:
        bw_p.setdefault(e["week"], []).append(e[rkey])
    diffs = [(w, sum(bw_h[w]) / len(bw_h[w]) - sum(bw_p[w]) / len(bw_p[w]))
             for w in bw_h if w in bw_p]
    fmt("高壓−placebo(同週配對)", cluster_t(diffs))
    # 高壓 − 自身對照
    paired = [(e["week"], e[rkey] - e[ckey]) for e in H if e[ckey] is not None]
    fmt("高壓−自身非事件窗(配對)", cluster_t(paired))
    # 逐年
    for y in sorted({e["year"] for e in H}):
        fmt(f"  {y} 高壓組", cluster_t([(e["week"], e[rkey]) for e in H if e["year"] == y]))
    # 尾部集中度
    rs = sorted((e[rkey] for e in H), reverse=True)
    tot = sum(rs)
    if rs and tot > 0:
        print(f"  尾部:top-3 事件佔總報酬 {sum(rs[:3]) / tot:.0%}"
              f" (top-3 均 {sum(rs[:3])/3:+.1%}, 中位數 {rs[len(rs)//2]:+.2%})")
    return {"hi": st_h, "vs_placebo": cluster_t(diffs), "vs_self": cluster_t(paired)}


def main():
    os.makedirs(CACHE, exist_ok=True)
    top = universe()
    print(f"Universe: TWSE 上市普通股平均成交值前 {len(top)} 大(5 快照)")
    events = build_events(top)
    json.dump(events, open(os.path.join(CACHE, "events.json"), "w"))
    n_hi_bal = sum(1 for e in events if e["bal"] > 0)
    print(f"事件數 {len(events)}(餘額>0:{n_hi_bal});FinMind 請求 {REQ['finmind']} 次")
    ts = []
    trials = 0
    for rkey, ckey in (("r10", "ctl10"), ("r5", "ctl5")):
        for q in (0.10, 0.20):
            trials += 1
            st = report(events, q, rkey, ckey)
            if st and st["hi"]:
                ts.append((f"top{int(q*100)}%×{rkey}", st))
    print(f"\ntrials 總數(訊號切法×窗長)= {trials}(全部列於上,無隱藏變體)")
    best = max(ts, key=lambda x: x[1]["hi"][1]) if ts else None
    if best:
        tag, st = best
        m, t, n, nc = st["hi"]
        tp = st["vs_placebo"][1] if st["vs_placebo"] else 0.0
        tc = st["vs_self"][1] if st["vs_self"] else 0.0
        # 機制裁判=vs placebo(vs_self 混雜除息季節性,不得單獨救到 🟡):
        if t >= 2 and m - COST > 0 and tp >= 2:
            verdict = "🟢 過初篩"
        elif t >= 2 and m - COST > 0 and tp >= 1.5:
            verdict = "🟡 弱訊號(需更多驗證)"
        else:
            verdict = "❌ 無訊號(高壓組報酬未勝過 placebo=除息季普遍漲,非回補壓力)"
        print(f"最佳變體 {tag}: 高壓t={t:+.2f} 淨={m - COST:+.2%} "
              f"vs_placebo t={tp:+.2f} vs_self t={tc:+.2f} → {verdict}")


if __name__ == "__main__":
    main()
