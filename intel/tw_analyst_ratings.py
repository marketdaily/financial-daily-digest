"""台股分析師共識動向連接器(信息差引擎台股件·內容型第二件,對標美股 us_analyst)。

cnyes `tw_forecast` 分類 = 鉅亨自動化發布的 FactSet 分析師共識速報,兩種固定標題型:
  「鉅亨速報 - Factset 最新調查：台積電(2330-TW)目標價調升至3090元，幅度約3%」
  「鉅亨速報 - Factset 最新調查：聯電(2303-TW)EPS預估上修至4.7元，預估目標價為92.5元」
標題自帶股票代碼/方向/數值/幅度→確定性 regex 解析,零 LLM、免 key、免費。
全分類約 10 則/日、單頁 30 則≈3 天窗口,patrol 每晚一掃不會漏。

訊號定義(門檻比照 us_analyst:≥8% red、4-8% yellow):
  🔴 共識目標價調升/調降幅度 ≥8%
  🟡 共識目標價異動 4-8%;EPS 預估上修/下修(標題無幅度,一律 yellow 事實轉述)
  <4% 的目標價微調 = 共識漂移雜訊,丟棄。
red/yellow 是「值得注意程度」非方向,方向在訊號文字裡(調升/調降),沿用 signal_ledger 慣例。

用法:
  live 掃描(watchlist 命中+解析統計): python3 -m intel.tw_analyst_ratings scan
  patrol.py 每晚呼叫 scan(wl) 併入 by_code(signal_ledger 記錄時自動帶 price_at_signal)。
"""
import sys
import json
import re
import datetime
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
FEED = "https://news.cnyes.com/api/v3/news/category/tw_forecast"

# 名稱吃「：」或「(」之間的字段;代碼固定 (dddd-TW);數值允許千分位逗號與小數
_RE_TP = re.compile(
    r"([^（(：:，,\s]+)\((\d{4,5})-TW\)目標價調(升|降)至([\d,]+(?:\.\d+)?)元[，,]\s*幅度約(-?[\d.]+)%")
_RE_EPS = re.compile(
    r"([^（(：:，,\s]+)\((\d{4,5})-TW\)EPS預估(上|下)修至(-?[\d,]+(?:\.\d+)?)元[，,]\s*預估目標價為([\d,]+(?:\.\d+)?)元")

RED_PCT = 8.0     # 共識目標價異動幅度門檻(比照 us_analyst)
YELLOW_PCT = 4.0


def _num(s):
    return float(str(s).replace(",", ""))


def parse_title(title):
    """單一標題→事件 dict;非兩種固定型回 None。純函式,離線可測。"""
    m = _RE_TP.search(title or "")
    if m:
        name, code, verb, tp, pct = m.groups()
        return {"kind": "target_price", "code": code, "name": name,
                "direction": "up" if verb == "升" else "down",
                "target": _num(tp), "pct": abs(_num(pct))}
    m = _RE_EPS.search(title or "")
    if m:
        name, code, verb, eps, tp = m.groups()
        return {"kind": "eps_estimate", "code": code, "name": name,
                "direction": "up" if verb == "上" else "down",
                "eps": _num(eps), "target": _num(tp), "pct": None}
    return None


def level_for(ev):
    """事件→red/yellow/None(丟棄)。純函式。"""
    if ev["kind"] == "target_price":
        if ev["pct"] >= RED_PCT:
            return "red"
        if ev["pct"] >= YELLOW_PCT:
            return "yellow"
        return None
    return "yellow"  # eps_estimate:標題無幅度,一律事實轉述級


def format_line(s):
    if s["kind"] == "target_price":
        verb = "調升" if s["direction"] == "up" else "調降"
        sign = "+" if s["direction"] == "up" else "-"
        return (f"{s['name']}({s['code']}):FactSet共識目標價{verb}至{s['target']:g}元"
                f"({sign}{s['pct']:g}%)")
    verb = "上修" if s["direction"] == "up" else "下修"
    return (f"{s['name']}({s['code']}):FactSet共識EPS預估{verb}至{s['eps']:g}元"
            f"(目標價{s['target']:g}元)")


def _fetch(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _utcnow():
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


def fetch_events(hours=48, pages=2, _fetch_fn=None):
    """抓 tw_forecast 近 hours 小時事件。回 (events, stats);單頁失敗只跳過該頁(fail-soft)。
    stats={"fetched","parsed","unparsed"} 供 CLI/巡檢誠實回報解析覆蓋率。"""
    fetch_fn = _fetch_fn or (lambda page: json.loads(_fetch(f"{FEED}?limit=30&page={page}")))
    cutoff = _utcnow() - datetime.timedelta(hours=hours)
    events, seen_ids = [], set()
    stats = {"fetched": 0, "parsed": 0, "unparsed": 0}
    for page in range(1, pages + 1):
        try:
            data = fetch_fn(page)
        except Exception:
            continue
        for item in (data.get("items", {}) or {}).get("data", []) or []:
            # per-item 防護:單一畸形 item(None/型別錯亂)只算 unparsed,不准拖垮整批
            # (驗證者 F1:畸形逃出 per-page try 會讓好頁一起全丟且無痕跡)
            try:
                news_id = item.get("newsId")
                if news_id and news_id in seen_ids:  # F2:缺 id 不參與 dedup,不互吞
                    continue
                if news_id:
                    seen_ids.add(news_id)
                title = (item.get("title") or "").strip()
                if not title:
                    continue
                pub_ts = item.get("publishAt", 0)
                d = (datetime.datetime.fromtimestamp(pub_ts, datetime.timezone.utc)
                     .replace(tzinfo=None) if pub_ts else None)
                if d and d < cutoff:
                    continue
                stats["fetched"] += 1
                ev = parse_title(title)
                if not ev:
                    stats["unparsed"] += 1
                    continue
                stats["parsed"] += 1
                ev["date"] = (d or _utcnow()).strftime("%Y-%m-%d")
                ev["url"] = (f"https://news.cnyes.com/news/id/{news_id}"
                             if news_id else "https://news.cnyes.com")
                ev["title"] = title
                events.append(ev)
            except Exception:
                stats["unparsed"] += 1
    return events, stats


def scan(watchlist, hours=48, pages=2, _fetch_fn=None):
    """patrol 入口:回 watchlist 命中且達 red/yellow 門檻的事件 list(含 level)。
    watchlist = {code: name} 或 code 集合;請求全失敗回空 list(零錯誤防線)。"""
    try:
        events, stats = fetch_events(hours=hours, pages=pages, _fetch_fn=_fetch_fn)
    except Exception:
        return []
    # 格式漂移偵測器(驗證者 F3):cnyes 若改標題格式,訊號會永久歸零且外觀正常——
    # 抓得到但一則都解析不出=結構性異常,印警告讓 patrol cron log 留痕(夜巡 live 探針同步守)
    if stats["fetched"] >= 5 and stats["parsed"] == 0:
        print(f"⚠️ tw_analyst_ratings:抓到 {stats['fetched']} 則但 0 解析,cnyes 標題格式可能已變")
    out = []
    for ev in events:
        if ev["code"] not in watchlist:
            continue
        lv = level_for(ev)
        if not lv:
            continue
        ev = dict(ev, level=lv)
        out.append(ev)
    return out


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "scan"
    if cmd != "scan":
        print(__doc__)
        return 0
    from intel import patrol  # lazy:避免與 patrol 頂層互相 import
    wl = patrol.build_watchlist()
    try:
        events, stats = fetch_events()  # 單次抓取,命中/統計同一快照(驗證者 F4)
    except Exception as e:
        print(f"tw_forecast 抓取失敗:{e}")
        return 1
    print(f"tw_forecast 近48h:抓到 {stats['fetched']} 則,解析 {stats['parsed']},"
          f"不合固定型 {stats['unparsed']}")
    all_leveled = [dict(e, level=level_for(e)) for e in events if level_for(e)]
    hits = [e for e in all_leveled if e["code"] in wl]
    print(f"watchlist({len(wl)} 檔)命中且達門檻:{len(hits)} 則")
    for s in hits:
        print(f"  [{s['level']}] {format_line(s)}")
    print(f"(全市場達門檻 {len(all_leveled)} 則,含非 watchlist)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
