"""us_congress_trades 連接器——美國會議員股票交易揭露訊號(信息差引擎美股籌碼面補源)。

資料源:CongressInvests 免費快取 API(https://congressinfor-production.up.railway.app,
Senate EFD + House Clerk 官方揭露,6h 更新,實測 /trades 免 key 可打,一次抓全快取
本地按 ticker 分組,整天只打 ~6 次分頁,不逐檔查)。
2026-07-30 GitHub 星海挖礦(public-apis)發現,與 us_13f(季度機構)/us_insider(公司內部人)
互補的第三條獨立籌碼訊號:國會議員有立法/聽證資訊優勢,揭露依法可遲至 45 天。

訊號定義(用 disclosed 揭露日算窗口——tx_date 上游爬蟲有髒值不可信):
  🔴 群聚買進:同 ticker 30 天內 ≥2 位不同議員申報買進(跨黨派/跨院更罕見,不分)
  🔴 大額買進:單筆申報區間下限 ≥ $50,001 且 14 天內揭露(多數國會交易是 $1k-$15k 小額)
  🟡 一般買進:14 天內有任何議員申報買進
  🟡 大額賣出:區間下限 ≥ $50,001 且 14 天內揭露(賣出雜訊多,小額不記)
  ⚪ 其他(只記錄不打擾)

⚠️ 已知限制(2026-07-30 實測):免費快取凍在 2026-06-01(data_lag ~58 天,宣稱 6h 更新但
next_refresh 卡 0;POST /cache/refresh 要 Pro key)。scan() 有源級新鮮度守衛:資料緣
超過 STALE_DAYS 即回空+印警告,不會拿兩個月前的申報冒充「近14天訊號」。
鋪平升級路徑(自主學習部):①註冊免費 key(100 req/day)看快取是否變新 ②改抓 Senate EFD/
House Clerk 官方源 ③status() 已內建,接情報部 liveness 總表。

用法:
  單檔:   python3 -m intel.us_congress_trades NVDA
  源健康: python3 -m intel.us_congress_trades --status
  patrol: us_congress_trades.scan(watchlist) → {sym: {date, level, signal}}
"""
import os
import json
import datetime
import subprocess
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, ".us_congress_trades_cache.json")

BASE = "https://congressinfor-production.up.railway.app"
PAGE_LIMIT = 1000
MAX_PAGES = 8
BIG_AMOUNT_MIN = 50001       # 申報區間下限 ≥ 此值算大額
FRESH_DAYS = 14              # 「近期」揭露窗口
CLUSTER_DAYS = 30            # 群聚買進窗口
CLUSTER_MIN_MEMBERS = 2
STALE_DAYS = 21              # 資料緣(最新揭露日)距今超過此天數=殭屍源,scan 回空+警告


def _fetch_curl(url, timeout=20):
    """.gov / .gov.tw 等憑證鏈驗證失敗的網域用這個,不要用 urllib。"""
    r = subprocess.run(["curl", "-s", "--max-time", str(timeout), url],
                        capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout:
        raise RuntimeError(f"curl failed rc={r.returncode} url={url}")
    return r.stdout


def _fetch_urllib(url, timeout=20):
    """一般網域用這個。UA 用完整版本字串——裸 "Mozilla/5.0" 會被部分 WAF(如 FRED)當機器人特徵擋下。"""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode()


def _load_cache():
    try:
        with open(CACHE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cache(cache):
    try:
        with open(CACHE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False)
    except Exception:
        pass


def _parse_amount_min(amount_str):
    """'$1,001 - $15,000' → 1001;解析失敗回 0(當小額,不誤升級)。"""
    try:
        low = str(amount_str).split("-")[0]
        return int(low.replace("$", "").replace(",", "").strip())
    except Exception:
        return 0


def _parse_date(s):
    try:
        return datetime.date.fromisoformat(str(s)[:10])
    except Exception:
        return None


def _fetch_all_by_ticker(today):
    """分頁抓完整快取(~5-6k 筆),本地按 ticker 分組。同日重複呼叫走檔案快取。"""
    cache = _load_cache()
    ck = f"_all:{today.isoformat()}"
    if ck in cache:
        return cache[ck]

    rows = []
    offset = 0
    for _ in range(MAX_PAGES):
        raw = json.loads(_fetch_urllib(f"{BASE}/trades?limit={PAGE_LIMIT}&offset={offset}"))
        rows.extend(raw.get("trades", []))
        if not raw.get("has_more"):
            break
        offset += PAGE_LIMIT
        time.sleep(0.4)

    by_ticker = {}
    for t in rows:
        sym = str(t.get("ticker", "")).upper().strip()
        if not sym:
            continue
        by_ticker.setdefault(sym, []).append({
            "member": t.get("member"),
            "chamber": t.get("chamber"),
            "trade_type": t.get("trade_type"),
            "amount_min": _parse_amount_min(t.get("amount")),
            "disclosed": str(t.get("disclosed", ""))[:10],
        })

    cache = {k: v for k, v in cache.items() if k.endswith(today.isoformat())}
    cache[ck] = by_ticker
    _save_cache(cache)
    return by_ticker


def classify(trades, today):
    """純函式:單一 ticker 的申報清單 → red/yellow/plain。
    trades: [{member, trade_type, amount_min, disclosed}],today: datetime.date。"""
    fresh_cut = (today - datetime.timedelta(days=FRESH_DAYS)).isoformat()
    cluster_cut = (today - datetime.timedelta(days=CLUSTER_DAYS)).isoformat()

    cluster_buyers, fresh_buys, big_fresh_buys, big_fresh_sells = set(), [], [], []
    for t in trades:
        d = t.get("disclosed", "")
        if not _parse_date(d):
            continue
        if t.get("trade_type") == "buy":
            if d >= cluster_cut:
                cluster_buyers.add(t.get("member"))
            if d >= fresh_cut:
                fresh_buys.append(t)
                if t.get("amount_min", 0) >= BIG_AMOUNT_MIN:
                    big_fresh_buys.append(t)
        elif t.get("trade_type") == "sell" and d >= fresh_cut and t.get("amount_min", 0) >= BIG_AMOUNT_MIN:
            big_fresh_sells.append(t)

    if len(cluster_buyers) >= CLUSTER_MIN_MEMBERS and fresh_buys:
        names = "、".join(sorted(x for x in cluster_buyers if x)[:3])
        return {"level": "red",
                "signal": f"國會群聚買進:{CLUSTER_DAYS}天內 {len(cluster_buyers)} 位議員申報買進({names})"}
    if big_fresh_buys:
        t = max(big_fresh_buys, key=lambda x: x.get("amount_min", 0))
        return {"level": "red",
                "signal": f"國會大額買進:{t.get('member')}({t.get('chamber')}) 申報 ≥${t.get('amount_min'):,}({t.get('disclosed')} 揭露)"}
    if fresh_buys:
        t = fresh_buys[0]
        return {"level": "yellow",
                "signal": f"國會議員買進:{t.get('member')}({t.get('chamber')}) {t.get('disclosed')} 揭露"}
    if big_fresh_sells:
        t = max(big_fresh_sells, key=lambda x: x.get("amount_min", 0))
        return {"level": "yellow",
                "signal": f"國會大額賣出:{t.get('member')}({t.get('chamber')}) 申報 ≥${t.get('amount_min'):,}({t.get('disclosed')} 揭露)"}
    return {"level": "plain", "signal": f"近{FRESH_DAYS}天無國會申報買賣"}


def congressinvests(key, today=None):
    """單一標的查詢,回 dict(含 date + classify() 結果)或 None(抓不到/查無資料)。"""
    today = today or datetime.date.today()
    key = str(key).upper().strip()
    cache = _load_cache()
    ck = f"{key}:{today.isoformat()}"
    if ck in cache:
        return cache[ck]

    try:
        by_ticker = _fetch_all_by_ticker(today)
    except Exception:
        return None
    trades = by_ticker.get(key)
    if trades is None:
        return None

    out = {"date": today.isoformat()}
    out.update(classify(trades, today))

    cache = _load_cache()
    cache = {k: v for k, v in cache.items() if k.endswith(today.isoformat())}
    cache[ck] = out
    _save_cache(cache)
    return out


def data_edge(by_ticker):
    """全表最新揭露日(str)或 None。"""
    dates = [t["disclosed"] for ts in by_ticker.values() for t in ts if _parse_date(t.get("disclosed", ""))]
    return max(dates) if dates else None


def status(today=None):
    """源健康:{data_edge, lag_days, stale}。接情報部 liveness 總表用。"""
    today = today or datetime.date.today()
    try:
        edge = data_edge(_fetch_all_by_ticker(today))
    except Exception:
        return {"data_edge": None, "lag_days": None, "stale": True}
    lag = (today - datetime.date.fromisoformat(edge)).days if edge else None
    return {"data_edge": edge, "lag_days": lag, "stale": lag is None or lag > STALE_DAYS}


def scan(keys, pause=0.0):
    """批次掃描,回 {key: result}。整包快取已在本地,逐 key 純查表,不再打 API(pause 保留介面相容)。
    源級新鮮度守衛:資料緣過期直接回空+印警告,不拿舊申報冒充近況(殭屍連接器要可見)。"""
    today = datetime.date.today()
    try:
        by_ticker = _fetch_all_by_ticker(today)
    except Exception:
        return {}
    edge = data_edge(by_ticker)
    if not edge or (today - datetime.date.fromisoformat(edge)).days > STALE_DAYS:
        print(f"⚠️ us_congress_trades 源過期:資料緣 {edge},超過 {STALE_DAYS} 天,本輪跳過(升級路徑見模組 docstring)")
        return {}
    out = {}
    for k in keys:
        sym = str(k).upper().strip()
        trades = by_ticker.get(sym)
        if trades is None:
            continue
        r = {"date": today.isoformat()}
        r.update(classify(trades, today))
        out[sym] = r
        if pause:
            time.sleep(pause)
    return out


if __name__ == "__main__":
    import sys
    if "--status" in sys.argv:
        print(json.dumps(status(), ensure_ascii=False, indent=1))
    else:
        key = sys.argv[1] if len(sys.argv) > 1 else "NVDA"
        print(json.dumps(congressinvests(key), ensure_ascii=False, indent=1))
