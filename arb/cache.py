"""抓取快取層。解的不是「不會爬」,是「一次爬太多被擋」。

行情資料一天查一次就夠(日拍成交是 30 日統計、台灣刊登也不會分鐘級變動),
所以快取不是妥協而是正確設計:
  1. 開發/除錯反覆執行時不重複打對方伺服器
  2. 每日排程只有第一次真的連線
  3. **被反爬擋住時可回退到快取的舊值,但一律標記 stale + 幾小時前**
     —— 絕不讓「被擋」變成「沒有資料」(本專案踩過:12/12 標的誤報零刊登)
"""
import hashlib
import json
import os
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(HERE, ".cache")
DEFAULT_TTL = 20 * 3600      # 20 小時:比每日排程間隔略短,確保每天真的更新一次


def _key(source, *parts):
    raw = source + "|" + "|".join(str(p) for p in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


def _path(k):
    return os.path.join(CACHE_DIR, k + ".json")


def get(source, *parts, ttl=DEFAULT_TTL):
    """回 (value, age_seconds) 或 (None, None)。age 供上層判斷新鮮度。"""
    p = _path(_key(source, *parts))
    if not os.path.exists(p):
        return None, None
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        return None, None
    age = time.time() - d.get("ts", 0)
    if ttl is not None and age > ttl:
        return None, age
    return d.get("value"), age


def get_stale(source, *parts):
    """不管 TTL 都拿——只在主源被擋、需要退而求其次時用。"""
    return get(source, *parts, ttl=None)


def put(source, *parts, value):
    os.makedirs(CACHE_DIR, exist_ok=True)
    p = _path(_key(source, *parts))
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"ts": time.time(), "src": source,
                   "parts": [str(x) for x in parts], "value": value},
                  f, ensure_ascii=False)
    os.replace(tmp, p)      # 原子寫入,避免半截檔被讀到
    return value


def cached(source, *parts, fetch, ttl=DEFAULT_TTL, accept=None):
    """有快取用快取;沒有就 fetch。

    accept(value) -> bool:判斷結果值不值得存。預設不存含 error 的結果,
    否則一次被擋就會把錯誤快取 20 小時。
    被擋(或 fetch 回 error)時回退到過期快取,並補上 stale 標記。
    """
    val, _ = get(source, *parts, ttl=ttl)
    if val is not None:
        return {**val, "_cache": "hit"} if isinstance(val, dict) else val

    fresh = fetch()
    ok = accept(fresh) if accept else not (isinstance(fresh, dict) and "error" in fresh)
    if ok:
        put(source, *parts, value=fresh)
        return {**fresh, "_cache": "miss"} if isinstance(fresh, dict) else fresh

    # 抓失敗 → 退回過期快取(標記 stale),沒有快取才回原始錯誤
    old, age = get_stale(source, *parts)
    if old is not None and isinstance(old, dict):
        return {**old, "_cache": "stale",
                "_stale_hours": round((age or 0) / 3600, 1),
                "_live_error": fresh.get("error") if isinstance(fresh, dict) else None}
    return fresh
