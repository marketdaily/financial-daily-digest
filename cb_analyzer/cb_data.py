"""標的現股資料:FinMind 抓收盤序列 → 波動率、近期漲跌;現價疊加 MIS 即時報價(cb_quote)。
盤中跑 → spot=即時價(spot_rt=True,附 spot_time);收盤後/抓不到即時 → 退回最後收盤價。
波動率一律用日線算(即時 tick 不進波動率)。"""
import os
import json
import math
import datetime
import urllib.request

import cb_quote

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
        tmp = CACHE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(c, f, ensure_ascii=False)
        os.replace(tmp, CACHE_PATH)
    except Exception:
        pass


def _ann_vol(rets):
    if len(rets) < 5:
        return None
    mean = sum(rets) / len(rets)
    var = sum((x - mean) ** 2 for x in rets) / (len(rets) - 1)
    return math.sqrt(var) * math.sqrt(252)


def _ewma_vol(rets, lam=0.94):
    """RiskMetrics EWMA 年化波動率(GARCH-lite,給近期較高權重但會均值回歸)。"""
    if len(rets) < 5:
        return None
    var = rets[0] ** 2
    for r in rets[1:]:
        var = lam * var + (1 - lam) * r * r
    return math.sqrt(var) * math.sqrt(252)


def blend_vol(vols, w_short=0.35, w_long=0.65):
    """前瞻波動估計:短期(EWMA)抓當前 regime、長期(120d)抓均值回歸錨。
    CB 選擇權存續 3~5 年 → 偏重長期。回 (blend, detail)。"""
    ewma = vols.get("ewma")
    v120 = vols.get("v120") or vols.get("v60")
    v60 = vols.get("v60")
    short = ewma or v60
    long = v120 or v60
    if short is None and long is None:
        return None, {}
    if short is None:
        return long, {"note": "僅長期"}
    if long is None:
        return short, {"note": "僅短期"}
    b = w_short * short + w_long * long
    return b, {"short": short, "long": long, "w_short": w_short, "w_long": w_long}


def get_stock(code, today=None, use_cache=True, vol_weights=(0.35, 0.65), realtime=True):
    """回 dict:spot, date, ret_20d, 多窗口波動(v20/v60/v120/ewma)+ vol_blend(前瞻估計)。失敗回 None。
    realtime=True 時疊加 MIS 即時報價:spot 換成最新成交/中價,原收盤留在 close_spot/close_date,
    spot_rt=True + spot_time 標時間戳;即時抓不到就維持收盤價(不加旗標)。"""
    out = _get_daily(code, today=today, use_cache=use_cache, vol_weights=vol_weights)
    if not out or not realtime:
        return out
    try:
        q = cb_quote.get_quote(code)
    except Exception:
        q = None
    if q and q.get("price") and q.get("date") and q["date"] >= out["date"]:
        out = dict(out)
        out["close_spot"], out["close_date"] = out["spot"], out["date"]
        out["spot"], out["date"] = q["price"], q["date"]
        out["spot_rt"], out["spot_time"], out["quote"] = True, q.get("time"), q
    return out


def _get_daily(code, today=None, use_cache=True, vol_weights=(0.35, 0.65)):
    today = today or datetime.date.today()
    cache = _load_cache() if use_cache else {}
    ckey = f"{code}:{today.isoformat()}:v3:{vol_weights}"
    if ckey in cache:
        return cache[ckey]

    start = (today - datetime.timedelta(days=400)).isoformat()
    try:
        rows = _finmind("TaiwanStockPrice", code, start)
    except Exception:
        return None
    closes = [(r.get("date"), r.get("close")) for r in rows
              if r.get("close") not in (None, 0)]
    closes = [(d, float(c)) for d, c in closes if c]
    if len(closes) < 10:
        return None
    closes.sort()
    px = [c for _, c in closes]
    allrets = [math.log(px[i] / px[i - 1]) for i in range(1, len(px)) if px[i - 1] > 0]

    def win(n):
        return _ann_vol(allrets[-n:]) if len(allrets) >= 5 else None
    vols = {
        "v20": win(20), "v60": win(60), "v120": win(120),
        "ewma": _ewma_vol(allrets[-120:] if len(allrets) >= 120 else allrets),
    }
    blend, detail = blend_vol(vols, vol_weights[0], vol_weights[1])
    ret_20d = (px[-1] / px[-21] - 1) if len(px) >= 21 else None
    out = {
        "code": code, "spot": px[-1], "date": closes[-1][0],
        "ret_20d": ret_20d, "n": len(allrets),
        "vols": vols, "vol_blend": blend, "vol_detail": detail,
        "hist_vol": vols["v60"],   # 相容舊欄位
        "closes": closes,   # [(date_iso, close), ...] 升冪排序,供強贖進度等逐日門檻計算使用
    }
    cache[ckey] = out
    if use_cache:
        _save_cache(cache)
    return out
