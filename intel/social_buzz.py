"""社群聲量連接器(社交套利內容層 v1,2026-07-11)。

背景:Chris Camillo 式社交套利=賺「人群已知、市場未察」的資訊時差。本連接器是 MarketDaily
的第一個社群/消費面訊號源(intel/ 既有 11+ 連接器全是官方/法規面),v1 三源:
  PTT 消費板(標題)、巴哈姆特(GNN 新聞+哈啦區首頁熱門)、Threads 官方 keyword_search API。
⚠️ Threads 需 app 具 threads_keyword_search 權限(2026-07-11 實測現有 token 無:HTTP 500 code:10,
要送 Meta App Review);權限下來前本源自動停用,PTT+巴哈先跑,token 權限到位即自動啟用,零改碼。

紀律(與既有連接器一致):
- 自成一體:不 import data_fetcher/main/analyzer,失敗一律靜默降級,絕不影響主管線。
- 觀察性質:產出只餵 analyzer prompt 的 reason 素材(_social_buzz_note),不改方向/價位建議。
- 先記帳後上桌:所有異常事件寫 events ledger,由 --evaluate 回填 1d/5d 前瞻報酬;
  聲量訊號未經 forward 驗證前,永不進正式 signal 邏輯/戰績(見報告 social_arbitrage/)。
- 冷啟動誠實:baseline 不足 MIN_BASELINE 天時不判異常(只累積計數),前一週輸出必然為空,正常。

計量設計:每日一次(winrig cron 18:40 TW)掃「今日」提及量→ledger;異常=該檔 total>=4 且
z-score>=2(對照近 21 筆、至少 7 筆的均值/標準差,std 下限 1 防除零與低基數誤報)。
每天同一時點掃,日與日之間才可比(不要再加第二個時段的 cron,會污染 baseline)。

用法:
  python3 -m intel.social_buzz            # 掃描+寫 ledger+產 latest.json
  python3 -m intel.social_buzz --evaluate # 回填 events 的 fwd_1d/fwd_5d(Yahoo 日線)
  python3 -m intel.social_buzz --stats    # 印 forward 驗證統計(樣本夠了才有意義)

關鍵字:預設=公司顯示名(scripts/.tw_names_cache.json);social_buzz_keywords.json 可逐檔覆寫
(加產品名/精確別名)。AMBIGUOUS_SKIP 內的高誤判名(統一/長榮…)無覆寫即跳過,寧缺勿錯。
"""
import os
import re
import json
import time
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
    # THREADS_ACCESS_TOKEN 住在 marketing/.env(auto_post.py 同源),不覆蓋 root 已有值
    load_dotenv(os.path.join(ROOT, "marketing", ".env"))
except Exception:
    pass

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
LEDGER = os.path.join(HERE, "social_buzz_ledger.jsonl")
EVENTS = os.path.join(HERE, "social_buzz_events.jsonl")
LATEST = os.path.join(HERE, "social_buzz_latest.json")
WATCHLIST_FILE = os.path.join(HERE, "social_buzz_watchlist.json")
KEYWORDS_FILE = os.path.join(HERE, "social_buzz_keywords.json")
WL_CACHE = os.path.join(HERE, "social_buzz_wl_cache.json")
NAMES_CACHE = os.path.join(ROOT, "scripts", ".tw_names_cache.json")

PTT_BOARDS = ["MobileComm", "e-shopping", "BeautySalon", "car", "Lifeismoney"]
PTT_MAX_PAGES = 12
MIN_BASELINE = 7
BASELINE_WINDOW = 21
Z_THRESHOLD = 2.0
MIN_COUNT = 4

# 高誤判公司短名:無 keywords 覆寫就整檔跳過,寧可漏掃不可髒訊號(zero-error 慣例)
AMBIGUOUS_SKIP = {"統一", "長榮", "第一", "中興", "大成", "全新", "中華", "台灣大"}


def _fetch(url, cookie=None, timeout=12):
    headers = {"User-Agent": UA}
    if cookie:
        headers["Cookie"] = cookie
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "ignore")


def _tw_today():
    """台灣時區的今天(winrig/Mac 都在 TW 時區,但 cron 環境不能賭,直接 UTC+8)。"""
    return (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=8)).date()


def _load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _name_map():
    return _load_json(NAMES_CACHE, {})


# ---------- watchlist ----------

def _subscriber_tw_codes():
    """日報訂閱者台股持股聯集(Brevo 名單→worker get-preferences)。任一步失敗回 None(用快取)。"""
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
        codes = set()
        for em in emails[:500]:
            try:
                body = json.dumps({"email": em}).encode()
                req = urllib.request.Request(f"{WORKER_URL}/get-preferences", data=body, method="POST",
                                             headers={"Content-Type": "application/json",
                                                      "Authorization": f"Bearer {tok}", "User-Agent": UA})
                with urllib.request.urlopen(req, timeout=10) as r:
                    d = json.loads(r.read())
                for s in d.get("tw_stocks") or []:
                    s = str(s).strip().upper().replace(".TW", "").replace(".TWO", "")
                    if s.isdigit() and 4 <= len(s) <= 6:
                        codes.add(s)
            except Exception:
                continue
        return codes or None
    except Exception:
        return None


def build_watchlist():
    """{code: 顯示名}=curated watchlist ∪ 訂閱者台股持股(best-effort,失敗用上次快取)。"""
    names = _name_map()
    wl = {}
    for c in _load_json(WATCHLIST_FILE, {}).get("codes", []):
        c = str(c)
        wl[c] = names.get(c, "")
    subs = _subscriber_tw_codes()
    if subs is not None:
        try:
            with open(WL_CACHE, "w", encoding="utf-8") as f:
                json.dump(sorted(subs), f, ensure_ascii=False)
        except Exception:
            pass
    else:
        subs = set(_load_json(WL_CACHE, []))
    for c in subs:
        wl.setdefault(c, names.get(c, ""))
    return {c: n for c, n in wl.items() if n or c in _load_json(KEYWORDS_FILE, {})}


def keywords_for(code, name, overrides):
    if code in overrides:
        return [k for k in overrides[code] if len(k) >= 2]
    name = (name or "").strip()
    if len(name) < 2 or name in AMBIGUOUS_SKIP:
        return []
    return [name]


# ---------- sources ----------

def scan_ptt():
    """回今日(TW)各消費板標題 list。單板失敗跳過,全失敗回空 list。"""
    today = _tw_today()
    want_date = f"{today.month}/{today.day}"
    titles = []
    for board in PTT_BOARDS:
        url = f"https://www.ptt.cc/bbs/{board}/index.html"
        try:
            for _ in range(PTT_MAX_PAGES):
                h = _fetch(url, cookie="over18=1")
                rows = re.findall(
                    r'<div class="title">\s*(?:<a href="[^"]+">([^<]+)</a>)?.*?'
                    r'<div class="date">\s*([\d/ ]+?)\s*</div>', h, re.S)
                page_dates = set()
                for title, d in rows:
                    d = d.strip()
                    page_dates.add(d)
                    if d == want_date and title and "本文已被刪除" not in title:
                        titles.append(title.strip())
                prev = re.search(r'href="(/bbs/' + board + r'/index\d+\.html)"[^>]*>&lsaquo; 上頁', h)
                # 整頁都不是今天(且有解析到日期)= 已翻過昨天,停
                if not prev or (page_dates and want_date not in page_dates):
                    break
                url = "https://www.ptt.cc" + prev.group(1)
                time.sleep(1.0)  # 禮貌爬取
        except Exception:
            continue
    return titles


def scan_bahamut():
    """回 GNN 新聞標題 + 哈啦區首頁熱門串/板名 list(每日同時點快照,日間可比)。"""
    titles = []
    try:
        g = _fetch("https://gnn.gamer.com.tw/")
        titles += [t.strip() for t in re.findall(
            r'<a[^>]+href="[^"]*detail\.php\?sn=\d+"[^>]*>([^<]{6,80})</a>', g)]
    except Exception:
        pass
    try:
        h = _fetch("https://forum.gamer.com.tw/")
        for anchor in re.findall(r'<a [^>]*href="[^"]*(?:B|C)\.php[^"]*"[^>]*>(.*?)</a>', h, re.S):
            text = re.sub(r"<[^>]+>", " ", anchor)
            text = re.sub(r"\s+", " ", text).strip()
            if 2 <= len(text) <= 80 and "img" not in text:
                titles.append(text)
    except Exception:
        pass
    return titles


def _threads_count(keyword, token):
    """Threads keyword_search:回 (近24h貼文數, 樣本list)。權限/額度錯誤丟 PermissionError 給上層停源。"""
    q = urllib.parse.quote(keyword)
    url = (f"https://graph.threads.net/v1.0/keyword_search?q={q}&search_type=RECENT"
           f"&fields=id,text,timestamp&limit=50&access_token={urllib.parse.quote(token)}")
    try:
        data = json.loads(_fetch(url, timeout=15))
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "ignore")
        except Exception:
            pass
        # Meta 權限錯誤實測回 HTTP 500 code:10「does not have permission」,不能只攔 400/403
        if "permission" in body.lower() or "oauth" in body.lower():
            raise PermissionError(body[:120])
        return 0, []
    except Exception:
        return 0, []
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=24)
    n, samples = 0, []
    for p in data.get("data", []):
        ts = p.get("timestamp", "")
        try:
            d = datetime.datetime.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S").replace(
                tzinfo=datetime.timezone.utc)
        except Exception:
            continue
        if d >= cutoff:
            n += 1
            if len(samples) < 2 and p.get("text"):
                samples.append(p["text"][:40].replace("\n", " "))
    return n, samples


def scan_threads(all_keywords):
    """{keyword: (count, samples)}。無 token=靜默停用;首個權限錯誤即整源停用(不重複打)。
    ⚠️ 2026-07-11 實測:threads_keyword_search 標準權限只搜得到 app 用戶自己的貼文(結構性 0),
    公開內容要過 Meta App Review 拿 Advanced Access。核准前用 THREADS_SEARCH_ENABLED=1 閘門
    鎖住本源——否則 baseline 被結構性 0 污染,核准日起一週會噴假異常。核准後 .env 加旗標即啟用。"""
    if os.environ.get("THREADS_SEARCH_ENABLED", "").strip() != "1":
        return {}
    token = os.environ.get("THREADS_ACCESS_TOKEN", "").strip()
    if not token:
        return {}
    out = {}
    for kw in all_keywords:
        try:
            out[kw] = _threads_count(kw, token)
        except PermissionError as e:
            print(f"[threads] 無 keyword_search 權限,本源停用:{e}")
            return {}
        time.sleep(0.5)
    return out


# ---------- scan + anomaly ----------

def run_scan():
    today = _tw_today().isoformat()
    wl = build_watchlist()
    overrides = _load_json(KEYWORDS_FILE, {})
    kw_by_code = {c: keywords_for(c, n, overrides) for c, n in wl.items()}
    kw_by_code = {c: ks for c, ks in kw_by_code.items() if ks}
    print(f"watchlist {len(kw_by_code)} 檔(原始 {len(wl)},歧義名跳過 {len(wl) - len(kw_by_code)})")

    ptt_titles = scan_ptt()
    baha_titles = scan_bahamut()
    print(f"PTT 今日標題 {len(ptt_titles)} 則,巴哈快照 {len(baha_titles)} 則")
    all_kws = sorted({k for ks in kw_by_code.values() for k in ks})
    threads_hits = scan_threads(all_kws)
    print(f"Threads 覆蓋 {len(threads_hits)} 個關鍵字" if threads_hits else "Threads 停用(無 token/權限)")

    rows = {}
    for code, kws in kw_by_code.items():
        counts = {"ptt": 0, "bahamut": 0, "threads": 0}
        samples = []
        for kw in kws:
            for t in ptt_titles:
                if kw in t:
                    counts["ptt"] += 1
                    if len(samples) < 3:
                        samples.append("PTT:" + t[:40])
            for t in baha_titles:
                if kw in t:
                    counts["bahamut"] += 1
                    if len(samples) < 3:
                        samples.append("巴哈:" + t[:40])
            if kw in threads_hits:
                n, s = threads_hits[kw]
                counts["threads"] += n
                samples += ["Threads:" + x for x in s[: max(0, 3 - len(samples))]]
        rows[code] = {"date": today, "code": code, "name": wl.get(code, ""),
                      "counts": counts, "total": sum(counts.values()), "samples": samples}

    # ledger:同日重跑=覆蓋(保持每日一筆,baseline 才乾淨)
    hist = []
    if os.path.exists(LEDGER):
        with open(LEDGER, encoding="utf-8") as f:
            hist = [json.loads(l) for l in f if l.strip()]
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
    for code, row in rows.items():
        past = sorted(by_code_hist.get(code, []), key=lambda x: x["date"])[-BASELINE_WINDOW:]
        if len(past) < MIN_BASELINE:
            continue
        vals = [p["total"] for p in past]
        mean = sum(vals) / len(vals)
        var = sum((v - mean) ** 2 for v in vals) / len(vals)
        std = max(var ** 0.5, 1.0)
        z = (row["total"] - mean) / std
        if row["total"] >= MIN_COUNT and z >= Z_THRESHOLD:
            note = (f"{row['name']}({code}) 今日社群提及 {row['total']} 次"
                    f"(近{len(vals)}日均 {mean:.1f},z={z:.1f})")
            if row["samples"]:
                note += f"|例:{row['samples'][0]}"
            anomalies[code] = {"note": note, "total": row["total"], "baseline": round(mean, 1),
                               "z": round(z, 2), "samples": row["samples"]}
            with open(EVENTS, "a", encoding="utf-8") as f:
                f.write(json.dumps({"date": today, "code": code, "name": row["name"],
                                    "total": row["total"], "baseline": round(mean, 1),
                                    "z": round(z, 2), "samples": row["samples"],
                                    "fwd_1d": None, "fwd_5d": None}, ensure_ascii=False) + "\n")

    with open(LATEST, "w", encoding="utf-8") as f:
        json.dump({"date": today, "by_code": anomalies}, f, ensure_ascii=False, indent=1)
    print(f"異常 {len(anomalies)} 檔 → {os.path.basename(LATEST)}"
          + ("" if anomalies else "(baseline 未滿或無異常,冷啟動期屬正常)"))


# ---------- forward 驗證 ----------

def _yahoo_closes(code):
    """{date_iso: close}。上市 .TW 失敗退 .TWO;全失敗回 {}。"""
    for suf in (".TW", ".TWO"):
        try:
            j = json.loads(_fetch(
                f"https://query1.finance.yahoo.com/v8/finance/chart/{code}{suf}"
                f"?range=1mo&interval=1d", timeout=12))
            res = j["chart"]["result"][0]
            ts = res["timestamp"]
            closes = res["indicators"]["quote"][0]["close"]
            out = {}
            for t, c in zip(ts, closes):
                if c:
                    d = (datetime.datetime.fromtimestamp(t, datetime.timezone.utc)
                         + datetime.timedelta(hours=8)).date().isoformat()
                    out[d] = c
            if out:
                return out
        except Exception:
            continue
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
        code = e["code"]
        if code not in closes_cache:
            closes_cache[code] = _yahoo_closes(code)
            time.sleep(0.5)
        closes = closes_cache[code]
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


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--evaluate", action="store_true")
    ap.add_argument("--stats", action="store_true")
    a = ap.parse_args()
    if a.stats:
        stats()
    elif a.evaluate:
        evaluate()
    else:
        run_scan()
