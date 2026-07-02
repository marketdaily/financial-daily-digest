"""台股法人動向連接器(信息差引擎積木 #1)。
任何代碼可查:外資/投信每日淨買賣、連續買賣天數(streak)、5/20 日累計 → 可行動訊號。
資料源 FinMind(免 token 可用,有 token 更穩);當日快取避免重複打。
訊號定義(產出必須是訊號,不是資料堆):
  🔴 投信連 3 日以上買超(投信認養=台股短線最強先行訊號)
  🔴 外資連 5 日以上同向 / 外資+投信 20 日同向且量大
  🟡 20 日淨額顯著(±200 張)但未成連續型態
  ⚪ 中性(只記錄不打擾)
"""
import os, json, datetime, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, ".inst_cache.json")
FINMIND = "https://api.finmindtrade.com/api/v4/data"
TOKEN = os.environ.get("FINMIND_TOKEN", "").strip()


def _fetch(dataset, code, start):
    url = f"{FINMIND}?dataset={dataset}&data_id={code}&start_date={start}"
    if TOKEN:
        url += f"&token={TOKEN}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode()).get("data", [])


def _load_cache():
    try:
        with open(CACHE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _daily_nets(rows):
    """按日期彙整 外資/投信 淨買賣(張)。回 [(date, foreign, trust), ...] 舊到新。"""
    by_date = {}
    for x in rows:
        d = x.get("date")
        name = x.get("name")
        if name not in ("Foreign_Investor", "Investment_Trust"):
            continue
        net = (x.get("buy", 0) - x.get("sell", 0)) / 1000.0
        cur = by_date.setdefault(d, [0.0, 0.0])
        cur[0 if name == "Foreign_Investor" else 1] += net
    return [(d, v[0], v[1]) for d, v in sorted(by_date.items())]


def _streak(vals):
    """尾端連續同向天數(>0 買 / <0 賣,0 中斷)。回帶正負號的天數。"""
    n = 0
    for v in reversed(vals):
        if v > 0:
            if n < 0:
                break
            n += 1
        elif v < 0:
            if n > 0:
                break
            n -= 1
        else:
            break
    return n


def flow(code, today=None):
    """回 dict:5/20 日淨額、外資/投信 streak、訊號分級。抓不到回 None。"""
    today = today or datetime.date.today()
    cache = _load_cache()
    ck = f"{code}:{today.isoformat()}"
    if ck in cache:
        return cache[ck]
    start = (today - datetime.timedelta(days=60)).isoformat()
    try:
        rows = _fetch("TaiwanStockInstitutionalInvestorsBuySell", code, start)
    except Exception:
        return None
    daily = _daily_nets(rows)
    if not daily:
        return None
    f_vals = [x[1] for x in daily]
    t_vals = [x[2] for x in daily]
    out = {
        "date": daily[-1][0],
        "foreign_5d": round(sum(f_vals[-5:])),
        "foreign_20d": round(sum(f_vals[-20:])),
        "trust_5d": round(sum(t_vals[-5:])),
        "trust_20d": round(sum(t_vals[-20:])),
        "foreign_streak": _streak(f_vals),
        "trust_streak": _streak(t_vals),
    }
    out.update(_classify(out))
    cache = {k: v for k, v in cache.items() if k.endswith(today.isoformat())}
    cache[ck] = out
    try:
        with open(CACHE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False)
    except Exception:
        pass
    return out


def _classify(o):
    fs, ts = o["foreign_streak"], o["trust_streak"]
    tot20 = o["foreign_20d"] + o["trust_20d"]
    if ts >= 3:
        return {"level": "red", "signal": f"投信連 {ts} 日買超(認養訊號,20日淨買 {o['trust_20d']:+,} 張)"}
    if ts <= -3:
        return {"level": "red", "signal": f"投信連 {abs(ts)} 日賣超(棄養警訊,20日淨賣 {o['trust_20d']:+,} 張)"}
    if fs >= 5:
        return {"level": "red", "signal": f"外資連 {fs} 日買超(5日淨買 {o['foreign_5d']:+,} 張)"}
    if fs <= -5:
        return {"level": "red", "signal": f"外資連 {abs(fs)} 日賣超(5日淨賣 {o['foreign_5d']:+,} 張)"}
    if abs(tot20) >= 200:
        side = "買超" if tot20 > 0 else "賣超"
        return {"level": "yellow", "signal": f"法人 20 日淨{side} {tot20:+,} 張(未成連續型態)"}
    return {"level": "plain", "signal": "法人中性"}


def scan(codes, pause=0.4):
    """批次掃描,回 {code: flow_dict}。禮貌節流。"""
    out = {}
    for c in codes:
        r = flow(c)
        if r:
            out[c] = r
        time.sleep(pause)
    return out
