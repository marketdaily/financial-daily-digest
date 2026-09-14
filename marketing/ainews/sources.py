"""來源層:英文 AI 新聞聚合 + 跨源聚類。

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
    # (key, 顯示名, url, ai_only, 權威分)
    # ai_only=True 的源整個 feed 都是 AI 題材 → 免過相關性閘
    # ai_only=False 是通用科技/綜合源 → 必須過 rank.is_ai_relevant(),否則麻疹與 MagSafe 線材會混進來
    ("techcrunch_ai", "TechCrunch", "https://techcrunch.com/category/artificial-intelligence/feed/", True, 5),
    ("verge_ai", "The Verge", "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml", True, 5),
    ("venturebeat_ai", "VentureBeat", "https://venturebeat.com/category/ai/feed/", True, 4),
    ("wired_ai", "WIRED", "https://www.wired.com/feed/tag/ai/latest/rss", True, 5),
    ("mit_tr", "MIT Tech Review", "https://www.technologyreview.com/feed/", False, 5),
    ("mit_news_ai", "MIT News", "https://news.mit.edu/rss/topic/artificial-intelligence2", True, 4),
    ("decoder", "The Decoder", "https://the-decoder.com/feed/", True, 4),
    ("ainews_net", "AI News", "https://www.artificialintelligence-news.com/feed/", True, 3),
    ("marktechpost", "MarkTechPost", "https://www.marktechpost.com/feed/", True, 3),
    ("unite_ai", "Unite.AI", "https://www.unite.ai/feed/", True, 3),
    ("synced", "Synced", "https://syncedreview.com/feed/", True, 3),
    ("simonw", "Simon Willison", "https://simonwillison.net/atom/everything/", True, 4),
    ("openai", "OpenAI", "https://openai.com/news/rss.xml", True, 6),
    ("googleblog_ai", "Google", "https://blog.google/technology/ai/rss/", True, 6),
    ("deepmind", "Google DeepMind", "https://deepmind.google/blog/rss.xml", True, 6),
    ("huggingface", "Hugging Face", "https://huggingface.co/blog/feed.xml", True, 4),
    ("nvidia_blog", "NVIDIA", "https://blogs.nvidia.com/feed/", True, 4),
    ("microsoft_ai", "Microsoft", "https://blogs.microsoft.com/feed/", False, 4),
    ("meta_ai", "Meta", "https://about.fb.com/news/tag/artificial-intelligence/feed/", True, 5),
    ("arstechnica", "Ars Technica", "https://feeds.arstechnica.com/arstechnica/index", False, 5),
    ("engadget", "Engadget", "https://www.engadget.com/rss.xml", False, 3),
    ("ieee", "IEEE Spectrum", "https://spectrum.ieee.org/feeds/topic/artificial-intelligence.rss", True, 4),
    ("guardian_ai", "The Guardian", "https://www.theguardian.com/technology/artificialintelligenceai/rss", True, 4),
    ("techxplore_ai", "TechXplore", "https://techxplore.com/rss-feed/machine-learning-ai-news/", True, 3),
    ("cnbc_tech", "CNBC", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=19854910", False, 4),
    ("hn", "Hacker News", "https://hnrss.org/frontpage?points=200", False, 3),
    ("reddit_ai", "r/artificial", "https://www.reddit.com/r/artificial/top/.rss?t=day", True, 2),
    ("reddit_sing", "r/singularity", "https://www.reddit.com/r/singularity/top/.rss?t=day", True, 2),
    ("reddit_llama", "r/LocalLLaMA", "https://www.reddit.com/r/LocalLLaMA/top/.rss?t=day", True, 2),
]


_REDDIT_LOCK = __import__("threading").Lock()


def _get(url, timeout=20):
    ua = UA
    if "reddit.com" in url:
        # reddit 對通用瀏覽器 UA 會 429;且三條同時打只會活一條 → 序列化 + 間隔
        ua = f"web:ainews-aggregator:1.0 (contact: {_BRAND['handle']})"
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
        key, label, url, ai_only, auth = f
        try:
            raw = _get(url)
            items = _parse_rss(raw)
            return key, label, auth, ai_only, items, None
        except Exception as e:
            return key, label, auth, ai_only, [], f"{type(e).__name__}: {e}"

    with ThreadPoolExecutor(workers) as ex:
        for key, label, auth, ai_only, items, err in ex.map(one, feeds):
            kept = 0
            for it in items:
                if it["published"] is None:
                    continue
                age_h = (now - it["published"]).total_seconds() / 3600
                if age_h < -2 or age_h > fresh_hours:
                    continue
                raw_items.append({**it, "src": key, "src_label": label, "ai_only": ai_only,
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
        lead = max(c["sources"], key=lambda s: (s["authority"], -s["age_h"]))
        out.append({
            "key": hashlib.sha1(lead["url"].encode()).hexdigest()[:12],
            "title": lead["title"],
            "url": lead["url"],
            "summary": lead["summary"],
            "published": lead["published"].isoformat(),
            "age_h": lead["age_h"],
            "src_label": lead["src_label"],
            "authority": lead["authority"],
            "ai_only": any(s["ai_only"] for s in c["sources"]),
            "confluence": len({s["src"] for s in c["sources"]}),
            "also": sorted({s["src_label"] for s in c["sources"]} - {lead["src_label"]}),
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
