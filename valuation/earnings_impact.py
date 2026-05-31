"""日報財報/營收影響分析。
硬數字(YoY/MoM/累計YoY/連續成長)一律程式算,當「已核實事實」餵 LLM;
LLM 只在數字外圍潤飾,禁止自行產生營收數字。
- 台股月營收:FinMind(免費)。事件日閘門用 create_time(≈次月10號 真實公布日)。
- 美股季報:FMP stable(免費層),營收/EPS YoY。
CLI: python3 valuation/earnings_impact.py 2330 2454 AAPL
"""
import os, sys, json, time, urllib.request, urllib.error, datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    import stock_names
    def _name(code, hint=None): return stock_names.display_name(code, hint)
except Exception:
    def _name(code, hint=None): return hint or code

FINMIND = "https://api.finmindtrade.com/api/v4/data"
FMP = "https://financialmodelingprep.com/stable"
FMP_KEY = os.environ.get("FMP_API_KEY", "")
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")
# 公布日(create_time/filingDate)到日報能涵蓋的天數:月營收約 10 號公布,給足裕度
EVENT_WINDOW_DAYS = 12
# 台股季報法定申報期限(金控除外) — 預告下一觀察點用真實排程
Q_DEADLINES = [(3, 31, "去年年報"), (5, 15, "Q1 季報"), (8, 14, "Q2 季報"), (11, 14, "Q3 季報")]


def _http_json(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def next_report_point(today):
    for m, d, label in Q_DEADLINES:
        dl = datetime.date(today.year, m, d)
        if dl >= today:
            return f"{dl.isoformat()} {label}"
    return f"{today.year + 1}-03-31 去年年報"


def _verdict(yoy):
    if yoy is None:
        return "資料不足", "—"
    if abs(yoy) >= 15:
        return ("偏正面" if yoy > 0 else "偏負面"), "影響大"
    if abs(yoy) >= 5:
        return ("偏正面" if yoy > 0 else "偏負面"), "影響中等"
    return "中性", "影響有限"


def tw_impact(stock_id, today):
    try:
        rows = _http_json(f"{FINMIND}?dataset=TaiwanStockMonthRevenue&data_id={stock_id}&start_date=2023-01-01").get("data", [])
    except Exception:
        return None
    if not rows:
        return None
    rows.sort(key=lambda x: (x["revenue_year"], x["revenue_month"]))
    cur = rows[-1]
    cy, cm, crev = cur["revenue_year"], cur["revenue_month"], cur["revenue"]
    prev_y = next((x for x in rows if x["revenue_year"] == cy - 1 and x["revenue_month"] == cm), None)
    prev_m = rows[-2] if len(rows) >= 2 else None
    yoy = ((crev - prev_y["revenue"]) / prev_y["revenue"] * 100) if prev_y and prev_y["revenue"] else None
    mom = ((crev - prev_m["revenue"]) / prev_m["revenue"] * 100) if prev_m and prev_m["revenue"] else None
    # 累計YoY:今年至今 vs 去年同期累計
    cum_cur = sum(x["revenue"] for x in rows if x["revenue_year"] == cy and x["revenue_month"] <= cm)
    cum_prev = sum(x["revenue"] for x in rows if x["revenue_year"] == cy - 1 and x["revenue_month"] <= cm)
    cum_yoy = ((cum_cur - cum_prev) / cum_prev * 100) if cum_prev else None
    # 連續 YoY 正成長月數
    streak = 0
    for r in reversed(rows):
        py = next((x for x in rows if x["revenue_year"] == r["revenue_year"] - 1 and x["revenue_month"] == r["revenue_month"]), None)
        if py and py["revenue"] and (r["revenue"] - py["revenue"]) > 0:
            streak += 1
        else:
            break
    # 事件日:用真實公布日 create_time(≈次月10號)
    is_event = False
    rel = cur.get("create_time")
    if rel:
        try:
            rd = datetime.date.fromisoformat(str(rel)[:10])
            is_event = 0 <= (today - rd).days <= EVENT_WINDOW_DAYS
        except Exception:
            pass
    verdict, impact = _verdict(yoy)
    return {
        "symbol": stock_id, "market": "tw", "name": _name(stock_id),
        "kind": "月營收", "period": f"{cy}/{cm}",
        "yoy": yoy, "mom": mom, "cum_yoy": cum_yoy, "streak": streak,
        "revenue_yi": round(crev / 1e8, 1),
        "base_effect": yoy is not None and abs(yoy) >= 100,
        "verdict": verdict, "impact": impact,
        "is_event": is_event, "release_date": str(rel)[:10] if rel else None,
        "next_point": next_report_point(today),
    }


def us_impact(symbol, today):
    if not FMP_KEY:
        return None
    try:
        rows = _http_json(f"{FMP}/income-statement?symbol={symbol}&period=quarter&limit=5&apikey={FMP_KEY}")
    except Exception:
        return None
    if not isinstance(rows, list) or len(rows) < 5:
        return None
    cur, yoy_q = rows[0], rows[4]  # 去年同季
    rev, rev_prev = cur.get("revenue"), yoy_q.get("revenue")
    eps, eps_prev = cur.get("epsDiluted") or cur.get("eps"), yoy_q.get("epsDiluted") or yoy_q.get("eps")
    yoy = ((rev - rev_prev) / rev_prev * 100) if rev and rev_prev else None
    eps_yoy = ((eps - eps_prev) / abs(eps_prev) * 100) if eps and eps_prev else None
    is_event = False
    fd = cur.get("filingDate") or cur.get("date")
    if fd:
        try:
            is_event = 0 <= (today - datetime.date.fromisoformat(str(fd)[:10])).days <= EVENT_WINDOW_DAYS
        except Exception:
            pass
    verdict, impact = _verdict(yoy)
    return {
        "symbol": symbol, "market": "us", "name": _name(symbol),
        "kind": "季報", "period": str(cur.get("date", ""))[:10],
        "yoy": yoy, "eps_yoy": eps_yoy, "streak": 0,
        "base_effect": yoy is not None and abs(yoy) >= 100,
        "verdict": verdict, "impact": impact,
        "is_event": is_event, "release_date": str(fd)[:10] if fd else None,
        "next_point": "下一季財報",
    }


def compute_impacts(us_symbols=None, tw_symbols=None, today=None, use_cache=True):
    """回傳 {symbol: facts};只算一次(全體持股聯集),日內快取。"""
    today = today or datetime.date.today()
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache_path = os.path.join(CACHE_DIR, "impacts.json")
    cache = {}
    if use_cache and os.path.exists(cache_path):
        try:
            c = json.load(open(cache_path, encoding="utf-8"))
            if c.get("date") == today.isoformat():
                cache = c.get("impacts", {})
        except Exception:
            pass
    out = {}
    for sym in (tw_symbols or []):
        if sym in cache:
            out[sym] = cache[sym]; continue
        f = tw_impact(sym, today)
        if f:
            out[sym] = f
        time.sleep(0.35)
    for sym in (us_symbols or []):
        if sym in cache:
            out[sym] = cache[sym]; continue
        f = us_impact(sym, today)
        if f:
            out[sym] = f
        time.sleep(0.2)
    try:
        json.dump({"date": today.isoformat(), "impacts": out}, open(cache_path, "w", encoding="utf-8"), ensure_ascii=False)
    except Exception:
        pass
    return out


def blurb(a):
    """事件日第二人稱喊話(deterministic;正式日報交 LLM 在這些數字外圍潤飾)。"""
    yoy = f"{a['yoy']:+.1f}%" if a.get("yoy") is not None else "—"
    base = "(低基期)" if a.get("base_effect") else ""
    streak = f"、已連 {a['streak']} 月正成長" if a.get("streak", 0) >= 2 else ""
    cum = f"、累計YoY {a['cum_yoy']:+.1f}%" if a.get("cum_yoy") is not None else ""
    name = a.get("name") or a["symbol"]
    return (f"・你追蹤的 {name}（{a['symbol']}）：{a['period']} {a['kind']} YoY {yoy}{base}{streak}{cum}"
            f" → 對你的部位{a['verdict']}（{a['impact']}）。接下來留意 {a['next_point']}。")


if __name__ == "__main__":
    args = sys.argv[1:] or ["2330"]
    today = datetime.date.today()
    tw = [s for s in args if s[0].isdigit()]
    us = [s for s in args if not s[0].isdigit()]
    res = compute_impacts(us, tw, today, use_cache=False)
    print(f"【財報影響分析】今天 {today.isoformat()}（FMP_KEY={'有' if FMP_KEY else '無'}）\n")
    for sym in args:
        a = res.get(sym)
        if not a:
            print(f"・{sym}：查無資料/被限流"); continue
        tag = "🔔事件日" if a.get("is_event") else "（非事件日,日報不喊）"
        print(blurb(a), tag)
