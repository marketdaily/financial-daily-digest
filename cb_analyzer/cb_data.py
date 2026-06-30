"""標的現股資料:FinMind 抓收盤序列 → 現價、年化歷史波動率、近期漲跌。免 token。"""
import os, json, math, datetime, urllib.request

FINMIND = "https://api.finmindtrade.com/api/v4/data"
FINMIND_TOKEN = os.environ.get("FINMIND_TOKEN", "").strip()
CACHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".price_cache.json")


def _finmind(dataset, data_id, start_date, timeout=20):
    url = f"{FINMIND}?dataset={dataset}&data_id={data_id}&start_date={start_date}"
    if FINMIND_TOKEN:
        url += f"&token={FINMIND_TOKEN}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode()).get("data", [])


def _load_cache():
    try:
        with open(CACHE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cache(c):
    try:
        with open(CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(c, f, ensure_ascii=False)
    except Exception:
        pass


def get_stock(code, today=None, window=60, use_cache=True):
    """回 dict: spot, hist_vol(年化小數), date, ret_20d, n。失敗回 None。"""
    today = today or datetime.date.today()
    cache = _load_cache() if use_cache else {}
    ckey = f"{code}:{today.isoformat()}:{window}"
    if ckey in cache:
        return cache[ckey]

    start = (today - datetime.timedelta(days=window * 2 + 40)).isoformat()
    try:
        rows = _finmind("TaiwanStockPrice", code, start)
    except Exception as e:
        return None
    closes = [(r.get("date"), r.get("close")) for r in rows
              if r.get("close") not in (None, 0)]
    closes = [(d, float(c)) for d, c in closes if c]
    if len(closes) < 10:
        return None
    closes.sort()
    px = [c for _, c in closes]
    # 年化歷史波動率:取最近 window 日 log return
    seg = px[-(window + 1):]
    rets = [math.log(seg[i] / seg[i - 1]) for i in range(1, len(seg)) if seg[i - 1] > 0]
    if len(rets) < 5:
        return None
    mean = sum(rets) / len(rets)
    var = sum((x - mean) ** 2 for x in rets) / (len(rets) - 1)
    hist_vol = math.sqrt(var) * math.sqrt(252)
    ret_20d = (px[-1] / px[-21] - 1) if len(px) >= 21 else None
    out = {
        "code": code, "spot": px[-1], "date": closes[-1][0],
        "hist_vol": hist_vol, "ret_20d": ret_20d, "n": len(rets),
    }
    cache[ckey] = out
    if use_cache:
        _save_cache(cache)
    return out
