"""Reddit 社群聲量連接器(社交套利內容層 v1 — 美股面,2026-07-22)。

背景:intel/ 的社交套利層原本只有 social_buzz.py(PTT/巴哈/Threads=台股中文社群面)。
本連接器補上「英文/美股散戶討論」這塊——對應 us_insider/us_8k/us_analyst 那一側,量測
Reddit 財經板(wallstreetbets/stocks/investing…)對某檔美股的**提及熱度異常**,抓 Chris
Camillo 式「人群已知、市場未察」的資訊時差。緣起:2026-07-22 一支 IG Reel 推坑「給 Claude
加 Reddit 存取」的 MCP,實查我們八成能力(YouTube 逐字稿/爬蟲/搜尋)早有,唯一真缺=Reddit。

⚠️ 存取現實(2026-07-22 實測):Reddit 早已封鎖匿名 .json(HTTP 403);匿名 .rss 偶爾 200
但一碰就 429,不夠穩當 cron 主路。唯一可靠免費路=官方 OAuth(script app,100 QPM)。
故本連接器與 social_buzz 的 Threads 源同構——**金鑰閘門,活化即用**:
  - .env 有 REDDIT_CLIENT_ID + REDDIT_CLIENT_SECRET(+ 既有 REDDIT_USER/REDDIT_PASS)→ 走 OAuth 主路。
  - 無 client 金鑰 → 退匿名 .rss best-effort(禮貌長 sleep + 單次退避);再失敗=靜默產空。
  金鑰未到位前輸出必然稀疏/空,屬冷啟動正常;金鑰一填自動走主路,零改碼。
  註冊方式:reddit.com/prefs/apps → create app → type 選 "script" → 複製 client id/secret 進 .env。

紀律(與 social_buzz / 既有連接器完全一致):
- 自成一體:不 import data_fetcher/main/analyzer;任何失敗靜默降級,絕不影響主管線。
- 觀察性質:產出只餵 analyzer prompt 的 reason 素材,不改方向/價位建議,不進 briefs/latest.json 可信層。
- 先記帳後上桌:異常寫 events ledger,由 --evaluate 回填 1d/5d 前瞻報酬;聲量訊號未經 forward
  驗證前永不進正式 signal 邏輯/戰績(與 social_buzz 相同的 walk-forward 誠實)。
- 冷啟動誠實:baseline 未滿 MIN_BASELINE 天不判異常(只累積計數),前一週輸出必然為空,正常。

計量設計:每日一次(建議 winrig cron,美股盤後固定時點)拉各板近況 feed,數「近 24h 提及該檔的
不重複貼文數」→ledger;異常=該檔 total>=MIN_COUNT 且 z-score>=Z_THRESHOLD(對照近 21 筆、
至少 7 筆的均值/標準差,std 下限 1 防除零與低基數誤報)。每天同一時點掃,日與日之間才可比。

用法:
  python3 -m intel.reddit_buzz            # 掃描+寫 ledger+產 latest.json
  python3 -m intel.reddit_buzz --evaluate # 回填 events 的 fwd_1d/fwd_5d(Yahoo 日線)
  python3 -m intel.reddit_buzz --stats    # 印 forward 驗證統計(樣本夠了才有意義)
  python3 -m intel.reddit_buzz --probe    # 檢查存取路徑(OAuth/RSS)通不通,列缺什麼金鑰
"""
import os
import re
import gzip
import json
import time
import base64
import argparse
import datetime
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
except Exception:
    pass

UA = "python:marketdaily.intel.reddit_buzz:v1 (by /u/marketdaily_bot)"
LEDGER = os.path.join(HERE, "reddit_buzz_ledger.jsonl")
EVENTS = os.path.join(HERE, "reddit_buzz_events.jsonl")
LATEST = os.path.join(HERE, "reddit_buzz_latest.json")
WATCHLIST_FILE = os.path.join(HERE, "us_watchlist.json")
WL_CACHE = os.path.join(HERE, "reddit_buzz_wl_cache.json")

SUBREDDITS = ["wallstreetbets", "stocks", "investing", "StockMarket", "options", "wallstreetbetsELITE"]
POSTS_PER_SUB = 100
WINDOW_HOURS = 24
MIN_BASELINE = 7
BASELINE_WINDOW = 21
Z_THRESHOLD = 2.0
MIN_COUNT = 3

# 也是常見英文字/財經縮寫的 ticker:只認 $ 前綴形(bare 形當雜訊丟),寧漏勿髒(zero-error 慣例)。
# 長度 1 的 ticker(A/F/V/T…)一律也只認 $ 形。
AMBIGUOUS = {
    "A", "I", "IT", "ON", "OR", "BE", "GO", "SO", "AN", "AT", "BY", "OK", "AM", "PM",
    "ALL", "ARE", "FOR", "NEW", "NOW", "ONE", "OUT", "CAN", "HAS", "HIS", "ANY", "SEE",
    "WHO", "BIG", "LOW", "GDP", "CPI", "FED", "SEC", "CEO", "CFO", "IPO", "ETF", "EPS",
    "AI", "EV", "US", "USA", "UK", "EU", "DD", "WSB", "ATH", "IMO", "TA", "PE", "OP",
    "YOLO", "HODL", "FOMO", "TLDR", "PSA", "EDIT", "FYI", "IRL", "EOD", "EOY", "YTD",
    "GG", "AF", "OG", "TWO", "REAL", "OPEN", "GOOD", "LOVE", "CASH", "HUGE", "PLAY",
    # 半導體/科技術語碰撞(既是行話也是 ticker,如 ADATA「DRAM shortage」誤判為 DRAM 個股)
    "DRAM", "RAM", "ARM", "CPU", "GPU", "CHIP", "NAND", "SSD", "HBM", "AR", "VR",
    # 常見英文單字型 ticker(逗號/大寫也會誤命中,只認 $ 形)
    "CAR", "GAS", "OIL", "SUN", "FUEL", "PLUG", "HOOD", "FUN", "WELL", "PLAN",
    "NICE", "TRUE", "TECH", "DATA", "FAST", "FLOW", "EYE", "RUN", "STEP",
}


def _fetch(url, headers=None, data=None, method=None, timeout=15):
    h = {"User-Agent": UA, "Accept-Encoding": "gzip"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
        return raw.decode("utf-8", "ignore")


def _tw_today():
    """記帳日鍵一律用 UTC 當日(美股盤 UTC 與 ET 同日;external API 日界用 UTC,見 feedback_utc_date_boundary)。"""
    return datetime.datetime.now(datetime.timezone.utc).date()


def _load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


# ---------- watchlist ----------

def _subscriber_us_symbols():
    """日報訂閱者美股持股聯集(Brevo 名單→worker get-preferences)。任一步失敗回 None(用快取)。"""
    brevo_key = os.environ.get("BREVO_API_KEY", "").strip()
    tok = os.environ.get("MARKETDAILY_INTERNAL_TOKEN", "").strip()
    if not brevo_key or not tok:
        return None
    try:
        from config_loader import WORKER_URL
    except Exception:
        return None
    try:
        req = urllib.request.Request("https://api.brevo.com/v3/contacts/lists",
                                     headers={"api-key": brevo_key, "User-Agent": UA})
        with urllib.request.urlopen(req, timeout=15) as r:
            lists = json.loads(r.read()).get("lists", [])
        list_id = lists[0]["id"] if lists else 2
        emails, offset = [], 0
        while True:
            req = urllib.request.Request(
                f"https://api.brevo.com/v3/contacts/lists/{list_id}/contacts?limit=500&offset={offset}",
                headers={"api-key": brevo_key, "User-Agent": UA})
            with urllib.request.urlopen(req, timeout=15) as r:
                contacts = json.loads(r.read()).get("contacts", [])
            emails += [c["email"] for c in contacts if c.get("email")]
            if len(contacts) < 500:
                break
            offset += 500
        syms = set()
        for em in emails[:500]:
            try:
                body = json.dumps({"email": em}).encode()
                req = urllib.request.Request(f"{WORKER_URL}/get-preferences", data=body, method="POST",
                                             headers={"Content-Type": "application/json",
                                                      "Authorization": f"Bearer {tok}", "User-Agent": UA})
                with urllib.request.urlopen(req, timeout=10) as r:
                    d = json.loads(r.read())
                for s in d.get("us_stocks") or []:
                    s = str(s).strip().upper()
                    if re.fullmatch(r"[A-Z]{1,5}", s):
                        syms.add(s)
            except Exception:
                continue
        return syms or None
    except Exception:
        return None


def build_watchlist():
    """盯的美股 ticker 集:config.US_STOCKS ∪ us_watchlist.json extra ∪ 訂閱者持股(best-effort,失敗用快取)。"""
    wl = set()
    try:
        import config
        wl |= {str(s).strip().upper() for s in getattr(config, "US_STOCKS", []) if s}
    except Exception:
        pass
    for it in _load_json(WATCHLIST_FILE, {}).get("extra", []):
        s = str(it.get("symbol", "")).strip().upper()
        if s:
            wl.add(s)
    subs = _subscriber_us_symbols()
    if subs is not None:
        try:
            with open(WL_CACHE, "w", encoding="utf-8") as f:
                json.dump(sorted(subs), f)
        except Exception:
            pass
    else:
        subs = set(_load_json(WL_CACHE, []))
    wl |= subs
    return {s for s in wl if re.fullmatch(r"[A-Z]{1,5}", s)}


# ---------- reddit access ----------

def _oauth_token():
    """script app password grant → bearer token;缺 client 金鑰或失敗回 None(上層退 RSS)。"""
    cid = os.environ.get("REDDIT_CLIENT_ID", "").strip()
    secret = os.environ.get("REDDIT_CLIENT_SECRET", "").strip()
    user = os.environ.get("REDDIT_USER", "").strip()
    pw = os.environ.get("REDDIT_PASS", "").strip()
    if not (cid and secret and user and pw):
        return None
    try:
        auth = base64.b64encode(f"{cid}:{secret}".encode()).decode()
        data = urllib.parse.urlencode(
            {"grant_type": "password", "username": user, "password": pw}).encode()
        body = _fetch("https://www.reddit.com/api/v1/access_token",
                      headers={"Authorization": f"Basic {auth}",
                               "Content-Type": "application/x-www-form-urlencoded"},
                      data=data, method="POST", timeout=15)
        return json.loads(body).get("access_token") or None
    except Exception:
        return None


def _posts_oauth(sub, token):
    """OAuth 主路:回該板近況貼文 [{title,text,ts,score,ncomments,id}]。失敗回 None(讓上層退 RSS)。"""
    url = f"https://oauth.reddit.com/r/{sub}/new?limit={POSTS_PER_SUB}&raw_json=1"
    try:
        body = _fetch(url, headers={"Authorization": f"bearer {token}"}, timeout=15)
        data = json.loads(body)
    except Exception:
        return None
    out = []
    for ch in data.get("data", {}).get("children", []):
        d = ch.get("data", {})
        out.append({"title": d.get("title", ""), "text": d.get("selftext", "")[:1500],
                    "ts": float(d.get("created_utc") or 0), "score": int(d.get("score") or 0),
                    "ncomments": int(d.get("num_comments") or 0), "id": d.get("id", "")})
    return out


_ATOM = "{http://www.w3.org/2005/Atom}"


def _posts_rss(sub):
    """匿名備援:.rss feed,429/空一律回 []。無精確分數/留言數(RSS 不含),補 0。"""
    import xml.etree.ElementTree as ET
    for attempt in range(2):
        try:
            body = _fetch(f"https://www.reddit.com/r/{sub}/new.rss?limit={POSTS_PER_SUB}", timeout=15)
            if not body.strip():
                raise ValueError("empty")
            root = ET.fromstring(body)
            out = []
            for e in root.findall(f"{_ATOM}entry"):
                title = (e.findtext(f"{_ATOM}title") or "")
                content = (e.findtext(f"{_ATOM}content") or "")
                pub = e.findtext(f"{_ATOM}published") or e.findtext(f"{_ATOM}updated") or ""
                ts = 0.0
                try:
                    ts = datetime.datetime.strptime(pub[:19], "%Y-%m-%dT%H:%M:%S").replace(
                        tzinfo=datetime.timezone.utc).timestamp()
                except Exception:
                    pass
                text = re.sub(r"<[^>]+>", " ", content)
                out.append({"title": title, "text": text[:1500], "ts": ts,
                            "score": 0, "ncomments": 0, "id": e.findtext(f"{_ATOM}id") or title})
            return out
        except Exception:
            time.sleep(5)  # 429 禮貌退避後再試一次
    return []


def gather_posts():
    """跨板拉近況貼文並依 id 去重。回 (posts, mode)。mode ∈ {oauth, rss, none}。"""
    token = _oauth_token()
    mode = "oauth" if token else "rss"
    seen, posts = set(), []
    for sub in SUBREDDITS:
        got = _posts_oauth(sub, token) if token else None
        if got is None:  # OAuth 對該板失敗 → 退 RSS
            got = _posts_rss(sub)
            if token:
                mode = "oauth+rss"
        for p in got:
            if p["id"] and p["id"] in seen:
                continue
            seen.add(p["id"])
            posts.append(p)
        time.sleep(1.5 if token else 6)  # OAuth 100QPM 寬鬆;匿名要非常禮貌
    if not posts:
        mode = "none"
    return posts, mode


# ---------- ticker matching ----------

def _matchers(symbol):
    """回 (cashtag_re, bare_re|None)。AMBIGUOUS 或長度1 只認 cashtag。"""
    cash = re.compile(r"\$" + re.escape(symbol) + r"\b", re.IGNORECASE)
    if symbol in AMBIGUOUS or len(symbol) < 2:
        return cash, None
    bare = re.compile(r"(?<![A-Za-z.$])" + re.escape(symbol) + r"(?![A-Za-z])")
    return cash, bare


def count_mentions(posts, watchlist):
    """回 {symbol: {"count": n, "samples": [..], "score": 累計upvote}}。近 WINDOW_HOURS 內貼文才計。"""
    cutoff = time.time() - WINDOW_HOURS * 3600
    recent = [p for p in posts if p["ts"] >= cutoff]
    mats = {s: _matchers(s) for s in watchlist}
    res = {s: {"count": 0, "samples": [], "score": 0} for s in watchlist}
    for p in recent:
        blob = (p["title"] or "") + "  " + (p["text"] or "")
        for s in watchlist:
            cash, bare = mats[s]
            if cash.search(blob) or (bare and bare.search(blob)):
                r = res[s]
                r["count"] += 1
                r["score"] += p["score"]
                if len(r["samples"]) < 3 and p["title"]:
                    tag = f"[{p['score']}⬆]" if p["score"] else ""
                    r["samples"].append(f"{tag}{p['title'][:60]}")
    return res, len(recent)


# ---------- scan + anomaly ----------

def run_scan():
    today = _tw_today().isoformat()
    watchlist = build_watchlist()
    print(f"美股 watchlist {len(watchlist)} 檔")
    posts, mode = gather_posts()
    print(f"Reddit 取得 {len(posts)} 則貼文(存取模式={mode})"
          + ("" if mode != "none" else " ⚠️ 匿名被擋且無 OAuth 金鑰,本輪空(冷啟動/待金鑰,正常)"))

    counts, n_recent = count_mentions(posts, watchlist)
    print(f"近 {WINDOW_HOURS}h 貼文 {n_recent} 則")

    rows = {}
    for sym, c in counts.items():
        rows[sym] = {"date": today, "code": sym, "name": sym,
                     "counts": {"reddit": c["count"]}, "total": c["count"],
                     "score": c["score"], "samples": c["samples"]}

    # ledger:同日重跑=覆蓋(每日一筆,baseline 才乾淨)。mode=none 時不寫(不污染 baseline)。
    hist = []
    if os.path.exists(LEDGER):
        with open(LEDGER, encoding="utf-8") as f:
            hist = [json.loads(l) for l in f if l.strip()]
    if mode != "none":
        hist = [r for r in hist if r.get("date") != today]
        hist += list(rows.values())
        with open(LEDGER, "w", encoding="utf-8") as f:
            for r in hist:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # anomaly:對照近 BASELINE_WINDOW 筆(不含今日)
    by_code_hist = {}
    for r in hist:
        if r["date"] != today:
            by_code_hist.setdefault(r["code"], []).append(r)
    anomalies = {}
    for sym, row in rows.items():
        past = sorted(by_code_hist.get(sym, []), key=lambda x: x["date"])[-BASELINE_WINDOW:]
        if len(past) < MIN_BASELINE:
            continue
        vals = [p["total"] for p in past]
        mean = sum(vals) / len(vals)
        var = sum((v - mean) ** 2 for v in vals) / len(vals)
        std = max(var ** 0.5, 1.0)
        z = (row["total"] - mean) / std
        if row["total"] >= MIN_COUNT and z >= Z_THRESHOLD:
            note = (f"{sym} 今日 Reddit 提及 {row['total']} 則"
                    f"(近{len(vals)}日均 {mean:.1f},z={z:.1f})")
            if row["samples"]:
                note += f"|例:{row['samples'][0]}"
            anomalies[sym] = {"note": note, "total": row["total"], "baseline": round(mean, 1),
                              "z": round(z, 2), "score": row["score"], "samples": row["samples"]}
            with open(EVENTS, "a", encoding="utf-8") as f:
                f.write(json.dumps({"date": today, "code": sym, "total": row["total"],
                                    "baseline": round(mean, 1), "z": round(z, 2),
                                    "score": row["score"], "samples": row["samples"],
                                    "fwd_1d": None, "fwd_5d": None}, ensure_ascii=False) + "\n")

    with open(LATEST, "w", encoding="utf-8") as f:
        json.dump({"date": today, "mode": mode, "by_code": anomalies}, f, ensure_ascii=False, indent=1)
    print(f"異常 {len(anomalies)} 檔 → {os.path.basename(LATEST)}"
          + ("" if anomalies else "(baseline 未滿或無異常,冷啟動期屬正常)"))


# ---------- forward 驗證 ----------

def _yahoo_closes(sym):
    """{date_iso: close}。美股 ticker 直用(無 .TW);失敗回 {}。"""
    try:
        j = json.loads(_fetch(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=1mo&interval=1d",
            timeout=12))
        res = j["chart"]["result"][0]
        ts = res["timestamp"]
        closes = res["indicators"]["quote"][0]["close"]
        out = {}
        for t, c in zip(ts, closes):
            if c:
                d = datetime.datetime.fromtimestamp(t, datetime.timezone.utc).date().isoformat()
                out[d] = c
        return out
    except Exception:
        return {}


def evaluate():
    """回填 events 的 fwd_1d/fwd_5d(訊號日收盤→之後第1/5個交易日收盤,%)。"""
    if not os.path.exists(EVENTS):
        print("無 events")
        return
    with open(EVENTS, encoding="utf-8") as f:
        evs = [json.loads(l) for l in f if l.strip()]
    changed = False
    closes_cache = {}
    for e in evs:
        if e.get("fwd_1d") is not None and e.get("fwd_5d") is not None:
            continue
        sym = e["code"]
        if sym not in closes_cache:
            closes_cache[sym] = _yahoo_closes(sym)
            time.sleep(0.5)
        closes = closes_cache[sym]
        days = sorted(closes)
        if e["date"] not in closes:
            continue
        base = closes[e["date"]]
        after = [d for d in days if d > e["date"]]
        if e.get("fwd_1d") is None and len(after) >= 1:
            e["fwd_1d"] = round((closes[after[0]] / base - 1) * 100, 2)
            changed = True
        if e.get("fwd_5d") is None and len(after) >= 5:
            e["fwd_5d"] = round((closes[after[4]] / base - 1) * 100, 2)
            changed = True
    if changed:
        with open(EVENTS, "w", encoding="utf-8") as f:
            for e in evs:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
    filled = sum(1 for e in evs if e.get("fwd_5d") is not None)
    print(f"events {len(evs)} 筆,fwd_5d 已回填 {filled}")


def stats():
    evs = [json.loads(l) for l in open(EVENTS, encoding="utf-8")] if os.path.exists(EVENTS) else []
    done = [e for e in evs if e.get("fwd_1d") is not None]
    if len(done) < 10:
        print(f"樣本 {len(done)} 筆(<10),統計無意義,繼續累積")
        return
    for horizon in ("fwd_1d", "fwd_5d"):
        vals = [e[horizon] for e in done if e.get(horizon) is not None]
        if not vals:
            continue
        win = sum(1 for v in vals if v > 0)
        print(f"{horizon}: n={len(vals)} 勝率={win/len(vals):.0%} 平均={sum(vals)/len(vals):+.2f}%")
    print("提醒:n<30 前不下結論;轉正式訊號需 walk-forward 且對照大盤同期。")


def probe():
    """檢查存取路徑通不通、缺哪把金鑰,不寫任何 ledger。"""
    have = {k: bool(os.environ.get(k, "").strip())
            for k in ("REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET", "REDDIT_USER", "REDDIT_PASS")}
    print("金鑰:" + ", ".join(f"{k}={'✓' if v else '✗'}" for k, v in have.items()))
    token = _oauth_token()
    if token:
        p = _posts_oauth("stocks", token)
        print(f"OAuth 主路:✓ token 取得,r/stocks 拉到 {len(p) if p else 0} 則")
        return
    if not (have["REDDIT_CLIENT_ID"] and have["REDDIT_CLIENT_SECRET"]):
        print("OAuth 主路:✗ 缺 REDDIT_CLIENT_ID/REDDIT_CLIENT_SECRET"
              "(reddit.com/prefs/apps → create app → 選 script → 複製兩把進 .env)")
    else:
        print("OAuth 主路:✗ 有 client 金鑰但換 token 失敗(檢查帳密/2FA/app type=script)")
    rss = _posts_rss("stocks")
    print(f"匿名 RSS 備援:{'✓ 拉到 %d 則' % len(rss) if rss else '✗ 被擋(429)或空'}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--evaluate", action="store_true")
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--probe", action="store_true")
    a = ap.parse_args()
    if a.probe:
        probe()
    elif a.stats:
        stats()
    elif a.evaluate:
        evaluate()
    else:
        run_scan()
