#!/usr/bin/env python3
"""P1.7 精準預判: buy 訊號 setup 條件化 edge 分析 (Delvin 2026-07-13 親令).

問題: buy 訊號在什麼 setup 條件下才有【正 edge】? (regime × 超賣/回檔 × 桶級 × 市場別)

方法鐵則 (feedback_math_rigor + 過去 lessons):
  1. 固定【預先登記】的 cut,不掃參 (無 overfitting 自由度).
  2. 基線不是 50%:buy win ⟺ chg>0,跌勢期 P(chg>0)<50% 天生負;用【真實宇宙基率】.
  3. day-cluster CI + eff_days≥15 誠實閘 (18 天資料,subset 會塌).
  4. 雙獨立透鏡,兩者皆過才算 edge:
       (A) hit-rate: edge_validator.assess (正確 baseline + day-cluster CI + episode fragility)
       (B) EV: backtest_validator.deflated_sharpe on【day-neutralized 每日 mean chg】,n_trials=K cuts
     day-neutralize = 減掉當日全宇宙 mean chg,剝除大盤 beta,只留【選股 selection edge】.
  5. 無 lookahead:所有技術特徵只用 ≤ 訊號日的價格.

輸出: 每個 cut 的 winrate/EV/eff_days/CI/DSR verdict + 條件化 buy 閘門提案.
不改 analyzer;純唯讀分析;等 Delvin 拍板.
"""
import json, os, sys, math, statistics
from collections import defaultdict, Counter
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
LEDGER = os.path.join(REPO, "scripts", "personal_ledger.jsonl")
PRICE_CACHE = os.path.join(REPO, "scripts", ".price_cache.json")
CAP = os.path.expanduser("~/autonomous/capabilities")
import importlib.util
def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m
ev = _load("ev_logic", os.path.join(CAP, "edge_validator", "logic.py"))       # assess
bt = _load("bt_logic", os.path.join(CAP, "backtest_validator", "logic.py"))    # metrics/DSR

REBUY_BLEED_PCT = 0.08   # 對齊 analyzer.py:857 生產閘門
REBUY_BLEED_DAYS = 5

# ---------- 資料 ----------
def load_rows():
    return [json.loads(l) for l in open(LEDGER) if l.strip()]

def load_prices():
    pc = json.load(open(PRICE_CACHE))
    out = {}
    for k, v in pc.items():
        if k.endswith("::history") and isinstance(v, dict):
            out[k[:-len("::history")]] = {d: float(p) for d, p in v.items()
                                          if isinstance(p, (int, float))}
    return out

def price_key(ticker, market):
    return f"{ticker}.TW" if market == "tw" else ticker

def series_upto(prices, key, d):
    """(dates, closes) up to and including d, ascending. No lookahead."""
    h = prices.get(key)
    if not h:
        return [], []
    items = sorted((dt, px) for dt, px in h.items() if dt <= d)
    return [x[0] for x in items], [x[1] for x in items]

# ---------- 技術特徵 (只用 ≤ 訊號日的價格) ----------
def rsi14(closes):
    if len(closes) < 15:
        return None
    gains = losses = 0.0
    for i in range(-14, 0):
        ch = closes[i] - closes[i - 1]
        if ch >= 0:
            gains += ch
        else:
            losses -= ch
    if losses == 0:
        return 100.0
    rs = (gains / 14) / (losses / 14)
    return 100 - 100 / (1 + rs)

def ma20(closes):
    return statistics.mean(closes[-20:]) if len(closes) >= 20 else None

def pullback_20d(closes):
    """(recent 20d high - last) / recent 20d high,回檔深度(0~1)."""
    if len(closes) < 5:
        return None
    window = closes[-20:] if len(closes) >= 20 else closes
    hi = max(window)
    return (hi - closes[-1]) / hi if hi > 0 else None

def add_features(rows, prices):
    for r in rows:
        key = price_key(r["ticker"], r["market"])
        _, closes = series_upto(prices, key, r["date"])
        r["_rsi"] = rsi14(closes)
        m = ma20(closes)
        r["_above_ma20"] = (closes[-1] > m) if (m and closes) else None
        r["_pullback"] = pullback_20d(closes)
    return rows

def add_rebuy_bleed(rows, prices):
    """系統級 (ticker,date) 重建 analyzer rebuy-bleed:同票 5 日曆日內發過 buy
    且現價較前次跌 ≥8% → flag。"""
    buy = [r for r in rows if r.get("verdict_class") == "buy"]
    # (ticker,date) 系統事件,dedupe 掉 per-user 重複
    events = sorted({(r["ticker"], r["market"], r["date"]) for r in buy})
    by_ticker = defaultdict(list)
    for t, mk, d in events:
        by_ticker[(t, mk)].append(d)
    bleed = set()  # (ticker, market, date)
    for (t, mk), dates in by_ticker.items():
        dates.sort()
        key = price_key(t, mk)
        for i, d in enumerate(dates):
            cur = None
            _, cl = series_upto(prices, key, d)
            if cl:
                cur = cl[-1]
            for j in range(i):
                pd = dates[j]
                gap = (date.fromisoformat(d) - date.fromisoformat(pd)).days
                if not (0 < gap <= REBUY_BLEED_DAYS):
                    continue
                _, clp = series_upto(prices, key, pd)
                ref = clp[-1] if clp else None
                if ref and cur and cur <= ref * (1 - REBUY_BLEED_PCT):
                    bleed.add((t, mk, d))
                    break
    for r in buy:
        r["_rebuy_bleed"] = (r["ticker"], r["market"], r["date"]) in bleed
    return bleed

# ---------- 基線: NON-BUY 宇宙 P(chg>0) + 每日 non-buy mean chg (day-neutralize 用) ----------
# 驗證者分離修正(2026-07-13):基線與 day-neutralize 的 benchmark 必須【排除 buy 自身】,
# 否則被測訊號落在自己的虛無假設裡(circular),neu-EV 被(1-buy占比)往零壓縮=系統性 flatter buy。
def universe_stats(rows):
    nonbuy = [r for r in rows if r.get("verdict_class") != "buy"]
    chg = [r["chg"] for r in nonbuy if isinstance(r.get("chg"), (int, float))]
    base_rate = sum(1 for c in chg if c > 0) / len(chg)          # P(chg>0) over non-buy
    day_mean = {}                                               # date -> mean chg (non-buy)
    byday = defaultdict(list)
    for r in nonbuy:
        if isinstance(r.get("chg"), (int, float)):
            byday[r["date"]].append(r["chg"])
    for d, cs in byday.items():
        day_mean[d] = statistics.mean(cs)
    return base_rate, day_mean

# ---------- eff_days (Herfindahl 有效獨立日) ----------
def eff_days(subset):
    byday = Counter(r["date"] for r in subset)
    n = sum(byday.values())
    return (n * n) / sum(v * v for v in byday.values()) if byday else 0.0

# ---------- 每個 cut 評估 ----------
def eval_cut(name, subset, base_rate, day_mean, n_trials):
    n = len(subset)
    if n == 0:
        return {"name": name, "n": 0, "verdict": "empty"}
    chg = [r["chg"] for r in subset if isinstance(r.get("chg"), (int, float))]
    wins = sum(1 for c in chg if c > 0)
    winrate = wins / len(chg)
    ev = statistics.mean(chg)
    ed = eff_days(subset)

    # 透鏡 A: hit-rate vs 正確基線
    a = ev_assess(subset, base_rate)

    # 透鏡 B: DSR on day-neutralized 每日 mean chg
    byday = defaultdict(list)
    for r in subset:
        if isinstance(r.get("chg"), (int, float)):
            byday[r["date"]].append(r["chg"])
    daily_raw, daily_neu = [], []
    for d in sorted(byday):
        m = statistics.mean(byday[d])
        daily_raw.append(m)
        daily_neu.append(m - day_mean.get(d, 0.0))   # 剝大盤 beta
    dsr = dsr_lens(daily_neu, n_trials)

    passed = (ed >= 15
              and a.get("verdict_honest") == "real_edge"
              and dsr.get("verdict") == "real_edge")
    return {
        "name": name, "n": n, "eff_days": round(ed, 2),
        "winrate": round(winrate * 100, 1), "base_rate": round(base_rate * 100, 1),
        "ev_pct": round(ev * 100, 2), "n_days": len(byday),
        "hit_verdict": a.get("verdict_honest"),
        "hit_ci": a.get("daycluster_ci"),
        "hit_naive_overstated": a.get("naive_overstated_confidence"),
        "episode_fragile": a.get("verdict_episode_fragile"),
        "degenerate": a.get("daycluster_degenerate"),
        "dsr_neu": dsr.get("dsr"), "dsr_verdict": dsr.get("verdict"),
        "daily_neu_mean_pct": round(statistics.mean(daily_neu) * 100, 3) if daily_neu else None,
        "PASS": passed,
    }

def ev_assess(subset, base_rate):
    recs = [{"label": ("win" if r["chg"] > 0 else "loss"), "date": r["date"]}
            for r in subset if isinstance(r.get("chg"), (int, float))]
    try:
        return ev.assess(recs, baseline_pct=base_rate * 100, episode_check=True)
    except Exception as e:
        return {"verdict_honest": f"error:{e}"}

def dsr_lens(daily_returns, n_trials):
    # 驗證者分離修正(2026-07-13):deflated_sharpe 在 T<10 機械式回傳 0.0(logic.py:141,
    # 三四階動差估不出),那不是「overfit」而是「樣本不足、DSR 未定義」。誠實標 underpowered,
    # 別讓它冒充「DSR 也說沒 edge」的第二透鏡佐證(對 <10 天的 cut 該透鏡無資訊)。
    if len(daily_returns) < 10:
        return {"dsr": None, "verdict": "underpowered(T<10)"}
    try:
        m = bt.metrics(daily_returns, n_trials=n_trials, ann=252)
        return {"dsr": round(m.get("DSR", 0), 3), "verdict": m.get("verdict")}
    except Exception as e:
        return {"dsr": None, "verdict": f"error:{e}"}

# ---------- 預先登記的 cut (固定,不掃參) ----------
def registered_cuts(buy):
    def has_rsi(r): return isinstance(r.get("_rsi"), (int, float))
    cuts = [
        ("all_buy", lambda r: True),
        ("non_rebuy_bleed", lambda r: r.get("_rebuy_bleed") is False),
        ("rebuy_bleed", lambda r: r.get("_rebuy_bleed") is True),
        ("regime_up", lambda r: r.get("regime") == "up"),
        ("regime_down", lambda r: r.get("regime") == "down"),
        ("prob_hi>=0.8", lambda r: isinstance(r.get("prob"), (int, float)) and r["prob"] >= 0.8),
        ("prob_lo<=0.4", lambda r: isinstance(r.get("prob"), (int, float)) and r["prob"] <= 0.4),
        ("market_tw", lambda r: r.get("market") == "tw"),
        ("market_us", lambda r: r.get("market") == "us"),
        ("oversold_rsi<30", lambda r: has_rsi(r) and r["_rsi"] < 30),
        ("dip_pullback>=10%", lambda r: isinstance(r.get("_pullback"), (int, float)) and r["_pullback"] >= 0.10),
        ("uptrend_above_ma20", lambda r: r.get("_above_ma20") is True),
        # 有先驗論點的合取
        ("uptrend_AND_prob>=0.7", lambda r: r.get("_above_ma20") is True and isinstance(r.get("prob"), (int, float)) and r["prob"] >= 0.7),
        ("dip_in_uptrend(rsi<40&above_ma)", lambda r: has_rsi(r) and r["_rsi"] < 40 and r.get("_above_ma20") is True),
    ]
    return cuts

def main():
    rows = load_rows()
    prices = load_prices()
    add_features(rows, prices)
    add_rebuy_bleed(rows, prices)
    base_rate, day_mean = universe_stats(rows)
    buy = [r for r in rows if r.get("verdict_class") == "buy"]

    cuts = registered_cuts(buy)
    K = len(cuts)
    results = []
    for name, pred in cuts:
        subset = [r for r in buy if pred(r)]
        results.append(eval_cut(name, subset, base_rate, day_mean, n_trials=K))

    out = {
        "generated": date.today().isoformat(),  # 2026-07-18 修:原寫死 "2026-07-13",重跑吃 live 帳本卻蓋舊章(date-literal 坑)
        "universe_base_rate_pct": round(base_rate * 100, 2),
        "n_buy": len(buy),
        "n_trials_multiplicity": K,
        "note_baseline": "buy win ⟺ chg>0; 基線=全宇宙 P(chg>0)，非 50%",
        "results": results,
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))
    # 摘要
    print("\n=== 摘要 (PASS = eff_days>=15 且 hit-rate real_edge 且 DSR real_edge) ===", file=sys.stderr)
    print(f"全宇宙基線 P(chg>0) = {base_rate*100:.1f}%  |  buy n={len(buy)}  |  多重檢定 K={K}", file=sys.stderr)
    for r in results:
        if r.get("n", 0) == 0:
            continue
        mark = "✅PASS" if r["PASS"] else "  ----"
        print(f"{mark} {r['name']:34s} n={r['n']:3d} effd={r['eff_days']:5.1f} "
              f"win={r['winrate']:4.1f}%(base {r['base_rate']:.1f}) EV={r['ev_pct']:+.2f}% "
              f"neuEV={r['daily_neu_mean_pct']:+.3f}%/d hit={r['hit_verdict']} dsr={r['dsr_verdict']}",
              file=sys.stderr)

if __name__ == "__main__":
    main()
