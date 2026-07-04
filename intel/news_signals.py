"""新聞事件訊號連接器(信息差引擎收尾:curriculum I 節最後一項「新聞+社群訊號整合」)。

既有 NEWS_API/cnyes 新聞管線(data_fetcher.py::fetch_us_news/fetch_tw_news)是餵 LLM prompt 的
原始文章堆;本連接器把同一批免費新聞源改走 intel 層既有模式——規則式關鍵字分級
(仿 alert-worker/src/index.js 的 EVENT_RULES,中英雙語才吃得到台股中文新聞),比對 watchlist
產生結構化 red/yellow by_code 訊號,不靠 LLM 判嚴重度,也不呼叫 data_fetcher.py(intel/ 連接器一律
自成一體,不依賴/不影響主管線,見既有 11 件連接器慣例)。

社群(X/政治人物發言)本應走 grok_political.py 的 xAI Live Search,但 XAI_API_KEY 迄今未設定
(見 memory project_grok_political_signals)。alert-worker 的既有共識是「政治人物市場級發言
幾分鐘內就會變 Reuters/CNBC 頭條」(見其 EVENT_RULES political 類註解),故此處改用同一份規則的
political/macro 廣域類型直接掃一般財經新聞,不綁 X 貼文——免費層一樣抓得到大半「社會/政策訊號」的
市場衝擊,只是抓不到「貼文本身」的第一手快訊速度。這是免費路徑下的誠實取捨,非 bug;若之後
XAI_API_KEY 到位,grok_political.py 可原封不動接上,兩者不衝突(不同資料源,可疊加)。

用法:
  python3 -m intel.news_signals            # 印三段結果(獨立 demo watchlist)
  scan_us(hours=36)      -> {ticker: {level, signal, source}}
  scan_tw(wl, hours=36)  -> {code: {level, signal, source}}  # wl 沿用 patrol.build_watchlist() 的 {code: name}
  broad_themes(hours=36) -> [{type, headline, url, date}]    # 市場級,非個股,不進 by_code
"""
import os
import re
import json
import datetime
import urllib.request
import urllib.parse

from intel import us_insider
from intel.us_sec_regulatory import _load_name_map, _core_tokens, _title_matches_company

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
try:
    # cron 環境沒有全域 export NEWS_API_KEY(同 valuation/ledger.py 對 FMP_API_KEY 的作法),
    # FinMind 系連接器不需這步是因為免 token 也能打;NEWS_API 是真的需要 key,必須自己讀 .env。
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
except Exception:
    pass

UA = "Mozilla/5.0"
NEWS_API_KEY = os.environ.get("NEWS_API_KEY", "").strip()
US_DOMAINS = ",".join([
    "reuters.com", "bloomberg.com", "wsj.com", "cnbc.com", "apnews.com", "ft.com",
    "marketwatch.com", "finance.yahoo.com", "investing.com", "seekingalpha.com",
    "businessinsider.com", "forbes.com", "barrons.com",
])
US_QUERY = "stock OR earnings OR fed OR tariff OR merger OR lawsuit OR downgrade OR bankruptcy"

# type -> (level, kw_en, kw_zh)。level=None 表示只作廣域主題(broad_themes),不比對個股 by_code。
COMPANY_RULES = [
    ("distress", "red",
     ["bankruptcy", "chapter 11", "insolvency", "files for bankruptcy", "delisted"],
     ["破產", "重整", "倒閉", "下市", "聲請破產"]),
    ("mna", "red",
     ["acquisition", "to acquire", "merger", "buyout", "takeover", "agrees to buy"],
     ["併購", "收購", "合併", "入股", "敵意併購"]),
    ("regulatory", "red",
     ["recall", "antitrust", "investigation", "probe", "subpoena", "raided", "fined"],
     ["調查", "罰款", "違規", "停牌", "裁罰", "搜索"]),
    ("legal", "red",
     ["lawsuit", "sues", "sued", "settlement", "court ruling"],
     ["訴訟", "提告", "敗訴", "勝訴", "判決", "和解"]),
    ("incident", "red",
     ["data breach", "hacked", "production halt", "explosion at", "fire at"],
     ["駭客", "資料外洩", "停工", "工安", "停產", "火警", "爆炸"]),
    ("guidance", "yellow",
     ["profit warning", "cuts guidance", "lowers outlook", "slashes forecast", "cuts forecast"],
     ["財測下修", "獲利警訊", "砍目標", "財測未達標"]),
    ("rating", "yellow",
     ["downgrade", "downgraded", "cut to sell", "price target cut"],
     ["調降評等", "降評", "目標價下修"]),
    ("leadership", "yellow",
     ["ceo resign", "steps down as ceo", "ousted", "fired as ceo"],
     ["執行長請辭", "執行長下台", "解任", "撤換"]),
    ("trading", "yellow",
     ["trading halted", "shares plunge", "shares crash", "shares tumble"],
     ["暫停交易", "股價重挫", "股價崩跌", "股價急殺"]),
]

# 一般財經新聞標題慣用「通俗簡稱」而非 SEC 官方登記全名(如 Meta 而非 Meta Platforms、
# TSMC 而非 Taiwan Semiconductor Manufacturing)——us_sec_regulatory 的 _core_tokens 對 SEC 官方
# filing 要求全詞比對是對的(SEC 公告本身就用全名),但直接套用在一般新聞會讓最常被報導的幾檔
# (META/AMZN/JPM/TSM)因全名多字要求反而比對失敗。US watchlist 檔數小(十餘檔),改用手動別名表,
# 查不到別名的 ticker(例如 us_watchlist.json 未來新增的標的)退回原本的官方全名嚴格比對當安全網。
US_ALIASES = {
    "AAPL": ["Apple"], "MSFT": ["Microsoft"], "GOOGL": ["Alphabet", "Google"],
    "AMZN": ["Amazon"], "META": ["Meta"], "NVDA": ["Nvidia"], "TSLA": ["Tesla"],
    "AMD": ["AMD", "Advanced Micro Devices"], "TSM": ["TSMC", "Taiwan Semiconductor"],
    "ARM": ["Arm Holdings"], "JPM": ["JPMorgan", "JP Morgan"], "GS": ["Goldman Sachs"],
    "BRK-B": ["Berkshire Hathaway"],
}


def _matches_ticker(title, ticker, core_tokens):
    """先試別名表(通俗簡稱,substring+大小寫不拘),查無別名才退回官方全名嚴格全詞比對。"""
    aliases = US_ALIASES.get(ticker)
    if aliases:
        low = title.lower()
        return any(a.lower() in low for a in aliases)
    return _title_matches_company(title, core_tokens)


BROAD_RULES = [
    ("political",
     ["white house", "tariff", "executive order", "export control", "export ban", "sanctions",
      "trade war", "trade deal", "chip ban"],
     ["白宮", "關稅", "行政命令", "出口管制", "禁令", "制裁", "貿易戰", "晶片禁令"]),
    ("macro",
     ["inflation data", "cpi report", "fed rate", "rate hike", "rate cut", "fomc", "jobs report",
      "recession fears"],
     ["通膨", "消費者物價", "升息", "降息", "利率決議", "非農", "衰退疑慮"]),
]


def _compile_rules(rules):
    out = []
    for row in rules:
        typ = row[0]
        level = row[1] if len(row) == 4 else None
        kw_en = row[-2]
        kw_zh = row[-1]
        pats = []
        if kw_en:
            pats.append(re.compile(r"\b(?:" + "|".join(re.escape(k) for k in kw_en) + ")", re.I))
        if kw_zh:
            pats.append(re.compile("(?:" + "|".join(re.escape(k) for k in kw_zh) + ")"))
        out.append((typ, level, pats))
    return out


_COMPANY_MATCHERS = _compile_rules(COMPANY_RULES)
_BROAD_MATCHERS = _compile_rules(BROAD_RULES)


def _classify(text, matchers):
    """回第一個命中的 (type, level);level 對 broad matchers 恆為 None。純函式,離線可測。"""
    for typ, level, pats in matchers:
        if any(p.search(text) for p in pats):
            return typ, level
    return None, None


def _fetch(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _utcnow():
    """naive UTC datetime,不用已棄用的 datetime.utcnow(),見 state/lessons tw_utc_date_boundary。"""
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


def _fetch_us_articles(hours=36):
    """NEWS_API everything(白名單財經站台+廣義關鍵字,單次呼叫省配額),回 [{title, url, date}] 新到舊。
    無 key 或請求失敗回空 list(零錯誤防線,不影響其他連接器)。"""
    if not NEWS_API_KEY:
        return []
    cutoff = _utcnow() - datetime.timedelta(hours=hours)
    q = urllib.parse.quote(US_QUERY)
    url = (
        f"https://newsapi.org/v2/everything?q={q}&domains={US_DOMAINS}"
        f"&language=en&sortBy=publishedAt&pageSize=100&apiKey={NEWS_API_KEY}"
    )
    try:
        data = json.loads(_fetch(url, timeout=20))
    except Exception:
        return []
    if data.get("status") != "ok":
        return []
    out = []
    for a in data.get("articles", []):
        title = (a.get("title") or "").strip()
        if not title:
            continue
        pub = a.get("publishedAt") or ""
        try:
            d = datetime.datetime.strptime(pub, "%Y-%m-%dT%H:%M:%SZ")
        except Exception:
            continue
        if d < cutoff:
            continue
        out.append({"title": title, "url": a.get("url", ""), "date": d})
    return out


def _fetch_tw_articles(hours=36):
    """cnyes.com 免 key 分類新聞(tw_stock+headline),回 [{title, url, date}] 新到舊。
    請求失敗回空 list。"""
    cutoff = _utcnow() - datetime.timedelta(hours=hours)
    out = []
    seen = set()
    for cat in ("tw_stock", "headline"):
        try:
            data = json.loads(_fetch(
                f"https://news.cnyes.com/api/v3/news/category/{cat}?limit=30", timeout=15))
        except Exception:
            continue
        for item in data.get("items", {}).get("data", []):
            title = (item.get("title") or "").strip()
            if not title or title in seen:
                continue
            pub_ts = item.get("publishAt", 0)
            d = datetime.datetime.fromtimestamp(pub_ts, datetime.timezone.utc).replace(tzinfo=None) if pub_ts else None
            if d and d < cutoff:
                continue
            seen.add(title)
            news_id = item.get("newsId", "")
            url = f"https://news.cnyes.com/news/id/{news_id}" if news_id else "https://news.cnyes.com"
            out.append({"title": title, "url": url, "date": d or _utcnow()})
    return out


def scan_us(hours=36):
    """回 {ticker: {level, signal, source}},比對 us_insider watchlist 官方公司名稱(復用
    us_sec_regulatory 的 name_map/token 比對,同一套規則兩處一致)。同碼多筆取最嚴重(red>yellow)、
    再取最新一則。"""
    wl = us_insider.build_watchlist()
    name_map = _load_name_map()
    core_by_ticker = {t: _core_tokens(name_map[t]) for t in wl if t in name_map}
    articles = _fetch_us_articles(hours)

    out = {}
    for a in articles:
        typ, level = _classify(a["title"], _COMPANY_MATCHERS)
        if level is None:
            continue
        for ticker, core in core_by_ticker.items():
            if not _matches_ticker(a["title"], ticker, core):
                continue
            existing = out.get(ticker)
            if existing is not None:
                if existing["_level"] == "red" and level == "yellow":
                    continue
                if existing["_level"] == level and existing["_date"] >= a["date"]:
                    continue
            out[ticker] = {
                "level": level, "source": "news_us", "_level": level, "_date": a["date"],
                "signal": f"{ticker} 新聞[{typ}]:{a['title'][:80]}",
            }
    return {t: {k: v for k, v in d.items() if not k.startswith("_")} for t, d in out.items()}


def scan_tw(wl, hours=36):
    """回 {code: {level, signal, source}}。wl={code: name}(沿用 patrol.build_watchlist() 現成結果,
    news_signals 不自建 TW watchlist 以免與 patrol.py 產生兩套不同步的清單/避免 circular import)。
    中文公司名比對用substring(中文字本身即 token,無 word boundary 問題,同 alert-worker 慣例)。"""
    articles = _fetch_tw_articles(hours)
    out = {}
    for code, name in (wl or {}).items():
        name = (name or "").strip()
        if len(name) < 2:
            continue
        for a in articles:
            if name not in a["title"]:
                continue
            typ, level = _classify(a["title"], _COMPANY_MATCHERS)
            if level is None:
                continue
            existing = out.get(code)
            if existing is not None:
                if existing["_level"] == "red" and level == "yellow":
                    continue
                if existing["_level"] == level and existing["_date"] >= a["date"]:
                    continue
            out[code] = {
                "level": level, "source": "news_tw", "_level": level, "_date": a["date"],
                "signal": f"{name}({code}) 新聞[{typ}]:{a['title'][:60]}",
            }
    return {c: {k: v for k, v in d.items() if not k.startswith("_")} for c, d in out.items()}


def broad_themes(hours=36):
    """市場級主題(政治/總經),非個股,不進 by_code。每個 type 只留最新一則代表性標題。
    回 list[{type, headline, url, date}] 依 date 新到舊。"""
    articles = _fetch_us_articles(hours) + _fetch_tw_articles(hours)
    articles.sort(key=lambda a: a["date"], reverse=True)
    seen_types = {}
    for a in articles:
        typ, _ = _classify(a["title"], _BROAD_MATCHERS)
        if typ is None or typ in seen_types:
            continue
        seen_types[typ] = {"type": typ, "headline": a["title"], "url": a["url"],
                            "date": a["date"].date().isoformat()}
    return sorted(seen_types.values(), key=lambda x: x["date"], reverse=True)


def format_broad_line(item):
    tag = {"political": "🌐政策", "macro": "🌐總經"}.get(item["type"], "🌐")
    return f"{tag}[{item['date']}] {item['headline']}"


if __name__ == "__main__":
    demo_wl = {"2330": "台積電", "2317": "鴻海", "2454": "聯發科"}
    us = scan_us()
    print(f"— 美股新聞事件訊號 {len(us)} 檔 —")
    for t, d in us.items():
        print(d["signal"])
    tw = scan_tw(demo_wl)
    print(f"\n— 台股新聞事件訊號(demo watchlist){len(tw)} 檔 —")
    for c, d in tw.items():
        print(d["signal"])
    broad = broad_themes()
    print(f"\n— 市場級主題 {len(broad)} 則 —")
    for b in broad:
        print(format_broad_line(b))
