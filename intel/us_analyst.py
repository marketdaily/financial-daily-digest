"""美股分析師動向連接器(信息差引擎積木 #4,美股信息源第一件)。
FMP grades-latest-news / price-target-latest-news 免費層只給「全市場最新 10 筆」且不能翻頁
(page=1 即 402),所以用跟 mops_watch 同一套路:全市場抓、過濾 watchlist、accumulate + dedup cache。
watchlist 為 config.US_STOCKS 大型活躍股,搭配高頻輪詢(cron */15,美股盤中時段)可穩定捕捉——
多數散戶不會逐則追蹤分析師調升調降,機器天天盯就是信息差。
訊號定義:
  🔴 評等調升/調降(previousGrade != newGrade,即真實 upgrade/downgrade;維持不變的雜訊丟棄)
  🔴 目標價異動 ≥ 8%(相對發布當下股價)
  🟡 目標價異動 4-8%
用法:
  輪詢一次(累積記帳,回傳本次新訊號): python3 -m intel.us_analyst poll
  今日/近N日訊號(供 patrol.py 併入夜間簡報): intel.us_analyst.todays_signals(days=2)
"""
import os, sys, json, datetime, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SEEN_CACHE = os.path.join(HERE, ".us_analyst_seen.json")
SIGNALS_LOG = os.path.join(HERE, "us_signals.jsonl")
WATCHLIST_EXTRA = os.path.join(HERE, "us_watchlist.json")

FMP = "https://financialmodelingprep.com/stable"
FMP_KEY = os.environ.get("FMP_API_KEY", "")

_GRADE_RANK = {
    "strong sell": 0, "sell": 1, "underperform": 1, "reduce": 1, "underweight": 1,
    "hold": 2, "neutral": 2, "market perform": 2, "equal weight": 2, "peer perform": 2, "sector perform": 2,
    "buy": 3, "outperform": 3, "overweight": 3, "accumulate": 3, "add": 3, "positive": 3,
    "strong buy": 4,
}


def _load_env_key():
    global FMP_KEY
    if FMP_KEY:
        return
    try:
        with open(os.path.join(ROOT, ".env"), encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("FMP_API_KEY="):
                    FMP_KEY = line.split("=", 1)[1].strip().strip('"').strip("'")
                    return
    except Exception:
        pass


def _default_watchlist():
    try:
        sys.path.insert(0, ROOT)
        import config
        return set(config.US_STOCKS)
    except Exception:
        return {"AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA",
                "AMD", "TSM", "ARM", "JPM", "GS", "BRK-B"}


def build_watchlist():
    wl = _default_watchlist()
    try:
        with open(WATCHLIST_EXTRA, encoding="utf-8") as f:
            extra = json.load(f)
        for x in extra.get("extra", []):
            sym = str(x.get("symbol", "")).upper().strip()
            if sym:
                wl.add(sym)
    except Exception:
        pass
    return wl


def _get(path, timeout=15):
    _load_env_key()
    url = f"{FMP}/{path}{'&' if '?' in path else '?'}apikey={FMP_KEY}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _grade_rank(g):
    return _GRADE_RANK.get((g or "").strip().lower(), 2)


def classify_grade_change(prev, new):
    """評等變動分級。回 None=雜訊(維持不變)不記,否則回 dict。"""
    if not prev or not new or prev.strip().lower() == new.strip().lower():
        return None
    direction = "upgrade" if _grade_rank(new) > _grade_rank(prev) else "downgrade"
    return {"direction": direction, "level": "red"}


def classify_price_target(price_when_posted, new_target):
    """目標價異動分級。回 None=低於門檻不記,否則回 dict(level,pct)。"""
    if not price_when_posted or not new_target:
        return None
    pct = (new_target - price_when_posted) / price_when_posted * 100
    if abs(pct) < 4:
        return None
    return {"level": "red" if abs(pct) >= 8 else "yellow", "pct": round(pct, 1)}


def _load_seen(path=SEEN_CACHE):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_seen(seen, path=SEEN_CACHE):
    cutoff = (datetime.date.today() - datetime.timedelta(days=14)).isoformat()
    seen = {k: v for k, v in seen.items() if v >= cutoff}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(seen, f, ensure_ascii=False)


def _append_signal(sig, path=SIGNALS_LOG):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(sig, ensure_ascii=False) + "\n")


def poll(seen_path=SEEN_CACHE, log_path=SIGNALS_LOG):
    """打一次全市場最新榜,過濾 watchlist,新訊號記帳。回傳本次新增訊號 list。"""
    wl = build_watchlist()
    seen = _load_seen(seen_path)
    today = datetime.date.today().isoformat()
    new_signals = []

    try:
        grades = _get("grades-latest-news?page=0&limit=10")
    except Exception as e:
        grades = []
        print(f"grades fetch fail: {e}", file=sys.stderr)
    for r in grades or []:
        sym = r.get("symbol")
        if sym not in wl:
            continue
        key = f"grade:{sym}:{r.get('publishedDate')}:{r.get('gradingCompany')}"
        if key in seen:
            continue
        seen[key] = today
        c = classify_grade_change(r.get("previousGrade"), r.get("newGrade"))
        if not c:
            continue
        sig = {
            "date": today, "type": "grade_change", "symbol": sym,
            "direction": c["direction"], "prev_grade": r.get("previousGrade"), "new_grade": r.get("newGrade"),
            "firm": r.get("gradingCompany"), "published": r.get("publishedDate"),
            "level": c["level"], "source": r.get("newsURL"),
        }
        new_signals.append(sig)
        _append_signal(sig, log_path)

    try:
        pts = _get("price-target-latest-news?page=0&limit=10")
    except Exception as e:
        pts = []
        print(f"price target fetch fail: {e}", file=sys.stderr)
    for r in pts or []:
        sym = r.get("symbol")
        if sym not in wl:
            continue
        key = f"pt:{sym}:{r.get('publishedDate')}:{r.get('analystCompany')}"
        if key in seen:
            continue
        seen[key] = today
        c = classify_price_target(r.get("priceWhenPosted"), r.get("priceTarget"))
        if not c:
            continue
        sig = {
            "date": today, "type": "price_target", "symbol": sym,
            "price_when_posted": r.get("priceWhenPosted"), "new_target": r.get("priceTarget"),
            "pct_change": c["pct"], "firm": r.get("analystCompany"), "published": r.get("publishedDate"),
            "level": c["level"], "source": r.get("newsURL"),
        }
        new_signals.append(sig)
        _append_signal(sig, log_path)

    _save_seen(seen, seen_path)
    return new_signals


def todays_signals(days=2, log_path=SIGNALS_LOG):
    """讀 us_signals.jsonl,回最近 N 天的訊號(給 patrol.py 併入夜間簡報)。"""
    cutoff = (datetime.date.today() - datetime.timedelta(days=days - 1)).isoformat()
    out = []
    try:
        with open(log_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                if row.get("date", "") >= cutoff:
                    out.append(row)
    except Exception:
        pass
    return out


def format_line(sig):
    sym = sig["symbol"]
    if sig["type"] == "grade_change":
        arrow = "⬆️" if sig["direction"] == "upgrade" else "⬇️"
        return f"🇺🇸 {sym} {arrow} {sig.get('prev_grade')}→{sig.get('new_grade')}({sig.get('firm')})"
    pct = sig.get("pct_change", 0)
    arrow = "⬆️" if pct > 0 else "⬇️"
    return f"🇺🇸 {sym} 目標價{arrow}{pct:+.1f}%→${sig.get('new_target')}({sig.get('firm')})"


if __name__ == "__main__":
    sigs = poll()
    if sigs:
        for s in sigs:
            print(format_line(s))
    else:
        print("no new signals this poll")
