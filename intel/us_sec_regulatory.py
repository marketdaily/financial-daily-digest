"""美股 SEC 法規監控連接器(信息差引擎第十一件,curriculum I 節最後一項:美股法規監控)。
跟台股兩件法規連接器(tw_surveillance=交易所端/tw_fsc=金管會端)同一維度的美股對應版,分兩段:
  ① scan_enforcement:SEC 行政程序公告(admin.xml,免key)比對 watchlist 官方公司名稱,
     命中=SEC 對這家公司本身開了正式行政程序,對持股者是硬訊號(仿 tw_fsc.py 同碼取最新)。
  ② scan_rule_changes:SEC 新聞稿(pressreleases.rss,免key)關鍵字篩出「規則變動」類標題
     (Adopts/Proposes/Rescinds+Rule/Regulation/Requirement/Disclosure),這類是市場級規則變化
     不對應單一個股,不進 by_code,純資訊性摘要供人工瀏覽。
兩個 RSS 都有 SEC 自己產出時未轉義的裸 `&`(如"Morgan Stanley & Co."),需先正規表達式修補再 parse,
否則 ET.fromstring 會 ParseError 整份掛掉(非偶發,兩個 feed 都會踩到)。
用法:
  python3 -m intel.us_sec_regulatory                  # 印兩段結果
  intel.us_sec_regulatory.scan_enforcement(days=90)   # {ticker: {level, signal, source}}
  intel.us_sec_regulatory.scan_rule_changes(days=14)  # [{date, title, link, level}]
"""
import os
import re
import json
import datetime
import urllib.request
import xml.etree.ElementTree as ET

from intel import us_insider

HERE = os.path.dirname(os.path.abspath(__file__))
NAME_CACHE = os.path.join(HERE, ".us_company_names.json")
NAME_CACHE_TTL_DAYS = 30

UA = "MarketDaily research contact@marketdaily.ai"
ADMIN_FEED = "https://www.sec.gov/rss/litigation/admin.xml"
PRESS_FEED = "https://www.sec.gov/news/pressreleases.rss"

SUFFIX_TOKENS = {"INC", "CORP", "CORPORATION", "CO", "COMPANY", "LTD", "LLC",
                  "PLC", "GROUP", "THE", "HOLDINGS", "HOLDING", "UK"}

RULE_KEYWORDS = ("ADOPTS", "PROPOSES", "RESCINDS", "RESCISSION", "AMENDMENTS", "FINAL RULE")
RULE_SUBJECTS = ("RULE", "RULES", "REGULATION", "REQUIREMENT", "REQUIREMENTS", "DISCLOSURE",
                  "REPORTING")
FINAL_KEYWORDS = ("ADOPTS", "RESCINDS", "RESCISSION", "FINAL RULE")


def _fetch(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _sanitize_xml(raw_bytes):
    """SEC 這兩個 RSS 的 title 常見未轉義裸 `&`(如"Morgan Stanley & Co."),
    合法 entity(&amp; &lt; &gt; &quot; &apos; &#123; &#x1F;)不動,其餘 `&` 補成 &amp;。純函式,離線可測。"""
    text = raw_bytes.decode("utf-8", errors="replace")
    fixed = re.sub(r"&(?!amp;|lt;|gt;|quot;|apos;|#\d+;|#x[0-9a-fA-F]+;)", "&amp;", text)
    return fixed.encode("utf-8")


def _parse_rss_items(xml_bytes):
    """回 list[{title, link, pub_date(date或None)}],壞資料回空 list。純函式,離線可測。"""
    out = []
    try:
        root = ET.fromstring(_sanitize_xml(xml_bytes))
    except ET.ParseError:
        return out
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub = (item.findtext("pubDate") or "").strip()
        d = _parse_rfc822_date(pub)
        if title:
            out.append({"title": title, "link": link, "date": d})
    return out


def _parse_rfc822_date(pub):
    """'Mon, 29 Jun 2026 17:44:53 -0400' → date(2026,6,29);解不出回 None。純函式,離線可測。"""
    try:
        # 只需日期部分,忽略時區細節(信息差用途不需要精確到秒)
        parts = pub.split()
        day, mon, year = int(parts[1]), parts[2], int(parts[3])
        months = {"Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
                  "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12}
        return datetime.date(year, months[mon], day)
    except Exception:
        return None


def _normalize_tokens(s):
    return [t for t in re.sub(r"[^A-Za-z0-9]+", " ", s.upper()).split() if t]


def _core_tokens(company_name):
    """去掉 INC/CORP/CO 等法人後綴留下有辨識度的詞;全被去掉時退回全部詞(防止空集合誤判全命中)。
    純函式,離線可測。"""
    toks = _normalize_tokens(company_name)
    core = [t for t in toks if t not in SUFFIX_TOKENS]
    return core or toks


def _title_matches_company(title, core_tokens):
    """core_tokens 全部以完整詞出現在 title 才算命中(非子字串比對,防止短詞誤判)。純函式,離線可測。"""
    if not core_tokens:
        return False
    title_tokens = set(_normalize_tokens(title))
    return all(t in title_tokens for t in core_tokens)


def _load_name_map(path=NAME_CACHE):
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
        age_days = (datetime.date.today() - datetime.date.fromisoformat(doc["_fetched"])).days
        if age_days <= NAME_CACHE_TTL_DAYS:
            return doc["map"]
    except Exception:
        pass
    return _refresh_name_map(path)


def _refresh_name_map(path=NAME_CACHE):
    """全市場 ticker→官方公司名稱(SEC 靜態檔,免key),只存我們用得到的欄位省空間。"""
    try:
        raw = json.loads(_fetch("https://www.sec.gov/files/company_tickers.json", timeout=30))
    except Exception:
        return {}
    m = {}
    for row in raw.values():
        t = str(row.get("ticker", "")).upper().strip()
        title = row.get("title")
        if t and title:
            m[t] = title
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"_fetched": datetime.date.today().isoformat(), "map": m}, f)
    return m


def scan_enforcement(days=90, name_map=None):
    """近 N 日 SEC 行政程序公告(admin.xml)比對 watchlist 官方名稱。
    回 {ticker: {level, signal, source}},同碼多筆取最新一則(全部訊號等級一致=red,
    watchlist 只十餘檔+公司被 SEC 正式開行政程序本身就罕見,無需分級,出現即視為紅燈)。"""
    cutoff = datetime.date.today() - datetime.timedelta(days=days)
    wl = us_insider.build_watchlist()
    name_map = name_map if name_map is not None else _load_name_map()
    core_by_ticker = {t: _core_tokens(name_map[t]) for t in wl if t in name_map}

    try:
        items = _parse_rss_items(_fetch(ADMIN_FEED))
    except Exception:
        return {}

    out = {}
    for it in items:
        if it["date"] is None or it["date"] < cutoff:
            continue
        for ticker, core in core_by_ticker.items():
            if _title_matches_company(it["title"], core):
                existing = out.get(ticker)
                if existing is not None and existing["date"] >= it["date"]:
                    continue
                out[ticker] = {
                    "level": "red", "source": "us_sec_admin", "date": it["date"],
                    "signal": f"{ticker} 美股SEC行政程序[{it['date'].isoformat()}]:{it['title'][:80]}",
                }
    return {t: {k: v for k, v in d.items() if k != "date"} for t, d in out.items()}


def _is_rule_change(title):
    """標題含規則動作字(Adopts/Proposes/Rescinds/Amendments/Final Rule)且含規則類名詞
    (Rule/Regulation/Requirement/Disclosure/Reporting)才算——排除人事任命/委員會會議等雜訊。
    純函式,離線可測。"""
    up = title.upper()
    return any(k in up for k in RULE_KEYWORDS) and any(s in up for s in RULE_SUBJECTS)


def _rule_change_level(title):
    """標題含 PROPOSES/SEEKS COMMENT 一律視為仍在提案階段(yellow),即使同時出現
    RESCISSION/ADOPTS 這類「聽起來已定案」的字(例如"Proposes Rescission of..."仍只是提案);
    只有明確 Adopts/Rescinds/Final Rule 且不含 Proposes 才算真正定案(red)。純函式,離線可測。"""
    up = title.upper()
    if "PROPOSES" in up or "PROPOSED" in up or "SEEKS COMMENT" in up or "SEEK COMMENT" in up:
        return "yellow"
    return "red" if any(k in up for k in FINAL_KEYWORDS) else "yellow"


def scan_rule_changes(days=30):
    """近 N 日 SEC 新聞稿(pressreleases.rss)篩出市場級規則變化(非個股,不進 by_code)。
    回 list[{date, title, link, level}],新到舊。"""
    cutoff = datetime.date.today() - datetime.timedelta(days=days)
    try:
        items = _parse_rss_items(_fetch(PRESS_FEED))
    except Exception:
        return []
    out = []
    for it in items:
        if it["date"] is None or it["date"] < cutoff:
            continue
        if not _is_rule_change(it["title"]):
            continue
        out.append({"date": it["date"].isoformat(), "title": it["title"], "link": it["link"],
                    "level": _rule_change_level(it["title"])})
    return out


def format_rule_change_line(rc):
    tag = "🔴已定案" if rc["level"] == "red" else "🟡提案中"
    return f"{tag}[{rc['date']}] {rc['title']}"


if __name__ == "__main__":
    enf = scan_enforcement()
    print(f"— 個股行政程序命中 {len(enf)} 檔 —")
    for t, d in enf.items():
        print(d["signal"])
    rules = scan_rule_changes()
    print(f"\n— 近期規則變化 {len(rules)} 則 —")
    for rc in rules:
        print(format_rule_change_line(rc))
