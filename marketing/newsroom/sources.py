"""來源層:世界新聞聚合 + 跨源聚類。

這個帳號是**世界新聞帳號**,不是 AI 帳號 —— AI/科技只是其中一條題材線。

設計要點(每條都是踩過的坑對應):
1. 每個來源獨立 try/except —— 一個 feed 掛掉不准讓整批變 0 筆(否則「今天沒新聞」
   與「抓取死了」分不出來,見 memory intel doctor 的致命歧義)。
2. fetch() 回傳 (items, health):health 逐源標 ok/筆數/錯誤,呼叫端必須看得到
   哪個源死了,不准只看總數。
3. 跨源聚類:同一則新聞被 N 家報導 = 熱度訊號,這是排序的主力特徵。
"""
import datetime
import hashlib
import re
import urllib.request
import urllib.error
import json
import pathlib as _pl

_BRAND = json.loads((_pl.Path(__file__).resolve().parent / "brand.json").read_text())
from concurrent.futures import ThreadPoolExecutor

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) Version/17.0 Safari/605.1.15")

# (key, 顯示名, url, kind, 權威分) —— 權威分只影響排序,不影響是否採用
FEEDS = [
    # (key, 顯示名, url, wire, 權威分)
    # ⚠️ 名稱後綴 "!" = 抓不到內文(Google News 轉址 / 付費牆)。
    # 這種源**仍然算跨源熱度**(它們報了就代表事情大),但**不准被選為代表文章** ——
    # 代表文章是我們要讀來寫稿的那一篇,選一篇讀不到的等於逼模型看著標題編故事。
    # 實測:不做這件事的話十則有六則因為代表文章讀不到而整則跳過。
    # wire=True ⇒ 通訊社/國際大報,整份 feed 都是新聞 → 免過「這是不是新聞」的閘
    # wire=False ⇒ 專業媒體或社群,混雜評論/教學/live blog → 必須過 rank.is_news()
    # ── 國際通訊社與大報(帳號的骨幹)──────────────────────────────────────
    ("bbc_world", "BBC", "https://feeds.bbci.co.uk/news/world/rss.xml", True, 6),
    ("bbc_top", "BBC", "https://feeds.bbci.co.uk/news/rss.xml", True, 6),
    ("reuters_wp", "Reuters!", "https://news.google.com/rss/search?q=when:12h+site:reuters.com&hl=en-US&gl=US&ceid=US:en", True, 6),
    ("ap_top", "AP!", "https://news.google.com/rss/search?q=when:12h+site:apnews.com&hl=en-US&gl=US&ceid=US:en", True, 6),
    ("aljazeera", "Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml", True, 5),
    ("guardian_world", "The Guardian", "https://www.theguardian.com/world/rss", True, 5),
    ("nyt_world", "NYT!", "https://rss.nytimes.com/services/xml/rss/nyt/World.xml", True, 6),
    ("npr", "NPR", "https://feeds.npr.org/1004/rss.xml", True, 5),
    ("cnn_world", "CNN", "http://rss.cnn.com/rss/edition_world.rss", True, 4),
    ("sky_world", "Sky News", "https://feeds.skynews.com/feeds/rss/world.xml", True, 4),
    ("dw", "DW", "https://rss.dw.com/rdf/rss-en-all", True, 4),
    ("france24", "France 24", "https://www.france24.com/en/rss", True, 4),
    ("abc_intl", "ABC News", "https://abcnews.go.com/abcnews/internationalheadlines", True, 4),
    # ── 亞洲(Threads 那一側是台灣讀者,亞洲新聞的權重要拉得起來)──────────
    ("nhk", "NHK World!", "https://news.google.com/rss/search?q=when:12h+site:nhk.or.jp&hl=en-US&gl=US&ceid=US:en", True, 5),
    ("kyodo", "Kyodo News!", "https://news.google.com/rss/search?q=when:12h+site:kyodonews.net&hl=en-US&gl=US&ceid=US:en", True, 4),
    ("scmp", "SCMP", "https://www.scmp.com/rss/91/feed", True, 4),
    ("straits", "Straits Times", "https://www.straitstimes.com/news/world/rss.xml", True, 4),
    ("toi_world", "Times of India", "https://timesofindia.indiatimes.com/rssfeeds/296589292.cms", True, 3),
    ("cna_intl", "中央社", "https://feeds.feedburner.com/rsscna/intworld", True, 4),
    ("cna_top", "中央社", "https://feeds.feedburner.com/rsscna/politics", True, 4),
    # ── 政治與衝突 ────────────────────────────────────────────────────────
    ("politico", "Politico", "https://rss.politico.com/politics-news.xml", True, 4),
    ("thehill", "The Hill", "https://thehill.com/news/feed/", True, 3),
    ("defensenews", "Defense News", "https://www.defensenews.com/arc/outboundfeeds/rss/", True, 3),
    # ── 商業與市場 ────────────────────────────────────────────────────────
    ("cnbc", "CNBC", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114", True, 4),
    ("ft_world", "FT!", "https://www.ft.com/world?format=rss", True, 5),
    ("bbc_business", "BBC", "https://feeds.bbci.co.uk/news/business/rss.xml", True, 5),
    # ── 科學與健康 ────────────────────────────────────────────────────────
    ("nature_news", "Nature", "https://www.nature.com/nature.rss", False, 5),
    ("sciencealert", "ScienceAlert", "https://www.sciencealert.com/feed", False, 3),
    ("space", "Space.com", "https://www.space.com/feeds/all", False, 3),
    # ── 科技/AI:一條線,不是整個帳號 ──────────────────────────────────────
    ("verge", "The Verge", "https://www.theverge.com/rss/index.xml", False, 5),
    ("techcrunch", "TechCrunch", "https://techcrunch.com/feed/", False, 4),
    ("arstechnica", "Ars Technica", "https://feeds.arstechnica.com/arstechnica/index", False, 5),
    ("hn", "Hacker News", "https://hnrss.org/frontpage?points=300", False, 3),
]


_REDDIT_LOCK = __import__("threading").Lock()


def _get(url, timeout=20):
    ua = UA
    if "reddit.com" in url:
        # reddit 對通用瀏覽器 UA 會 429;且三條同時打只會活一條 → 序列化 + 間隔
        ua = f"web:newsroom-aggregator:1.0 (contact: {_BRAND['handle']})"
        with _REDDIT_LOCK:
            import time as _t
            _t.sleep(2.0)
            req = urllib.request.Request(url, headers={"User-Agent": ua})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
    req = urllib.request.Request(url, headers={"User-Agent": ua})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _parse_rss(raw):
    import feedparser
    d = feedparser.parse(raw)
    out = []
    for e in d.entries[:40]:
        title = (e.get("title") or "").strip()
        link = (e.get("link") or "").strip()
        if not title or not link:
            continue
        ts = None
        for k in ("published_parsed", "updated_parsed"):
            if e.get(k):
                import calendar
                ts = datetime.datetime.fromtimestamp(
                    calendar.timegm(e[k]), datetime.timezone.utc)
                break
        summary = re.sub(r"<[^>]+>", " ", e.get("summary", "") or "")
        summary = re.sub(r"\s+", " ", summary).strip()[:600]
        out.append({"title": title, "url": link, "published": ts, "summary": summary})
    return out


_STOP = set("""a an and are as at be by for from has have how in is it its of on or that the
to was were what when who will with you your this these those new now say says said after
into over more most than then they their there here about can could would should over amid""".split())


def _keyset(title):
    words = re.findall(r"[a-z0-9][a-z0-9\-']+", title.lower())
    return {w for w in words if w not in _STOP and len(w) > 2}


def fetch(feeds=None, fresh_hours=30, workers=8):
    """回 (items, health)。items 已跨源聚類,每筆帶 sources[]。"""
    feeds = feeds or FEEDS
    now = datetime.datetime.now(datetime.timezone.utc)
    health, raw_items = [], []

    def one(f):
        key, label, url, wire, auth = f
        try:
            raw = _get(url)
            items = _parse_rss(raw)
            return key, label, auth, wire, items, None
        except Exception as e:
            return key, label, auth, wire, [], f"{type(e).__name__}: {e}"

    with ThreadPoolExecutor(workers) as ex:
        for key, label, auth, wire, items, err in ex.map(one, feeds):
            kept = 0
            for it in items:
                if it["published"] is None:
                    continue
                age_h = (now - it["published"]).total_seconds() / 3600
                if age_h < -2 or age_h > fresh_hours:
                    continue
                raw_items.append({**it, "src": key, "src_label": label, "wire": wire,
                                  "authority": auth, "age_h": round(age_h, 1)})
                kept += 1
            health.append({"src": key, "ok": err is None, "raw": len(items),
                           "fresh": kept, "error": err})

    # 跨源聚類:標題關鍵字 Jaccard >= 0.5 視為同一則
    clusters = []
    for it in sorted(raw_items, key=lambda x: x["age_h"]):
        ks = _keyset(it["title"])
        placed = False
        for c in clusters:
            inter = len(ks & c["keys"])
            union = len(ks | c["keys"]) or 1
            smaller = min(len(ks), len(c["keys"])) or 1
            if inter / union >= 0.5 or (inter >= 3 and inter / smaller >= 0.5):
                c["sources"].append(it)
                c["keys"] |= ks
                placed = True
                break
        if not placed:
            clusters.append({"keys": ks, "sources": [it]})

    out = []
    for c in clusters:
        # 代表文章:先挑讀得到的(名稱不帶 "!"),同樣讀得到才比權威分。
        # 讀不到的源仍留在 c["sources"] 裡,所以 confluence(熱度)完全不受影響。
        lead = max(c["sources"],
                   key=lambda s: (not s["src_label"].endswith("!"), s["authority"], -s["age_h"]))
        out.append({
            "key": hashlib.sha1(lead["url"].encode()).hexdigest()[:12],
            "title": lead["title"],
            "url": lead["url"],
            "summary": lead["summary"],
            "published": lead["published"].isoformat(),
            "age_h": lead["age_h"],
            "src_label": lead["src_label"].rstrip("!"),
            "lead_readable": not lead["src_label"].endswith("!"),
            "authority": lead["authority"],
            "wire": any(s["wire"] for s in c["sources"]),
            "confluence": len({s["src"] for s in c["sources"]}),
            "also": sorted({s["src_label"].rstrip("!") for s in c["sources"]}
                           - {lead["src_label"].rstrip("!")}),
        })
    return out, health


def health_summary(health):
    dead = [h for h in health if not h["ok"]]
    silent = [h for h in health if h["ok"] and h["raw"] == 0]
    return {"total": len(health), "dead": [h["src"] for h in dead],
            "silent_but_alive": [h["src"] for h in silent],
            "fresh_items": sum(h["fresh"] for h in health)}


if __name__ == "__main__":
    items, health = fetch()
    print(json.dumps(health_summary(health), ensure_ascii=False, indent=1))
    for h in health:
        if not h["ok"]:
            print(f"  ❌ {h['src']}: {h['error']}")
    print(f"\n聚類後 {len(items)} 則。confluence>=2 的前 15:")
    for it in sorted(items, key=lambda x: (-x["confluence"], -x["authority"], x["age_h"]))[:15]:
        print(f"  [{it['confluence']}源|{it['authority']}|{it['age_h']}h] {it['src_label']}: {it['title'][:90]}")
