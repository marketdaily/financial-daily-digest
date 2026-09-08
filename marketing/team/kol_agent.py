#!/usr/bin/env python3
"""BLACKEDGE 第 15 席:KOL 席。探索 → 評分 → 簡報 → 外聯草稿 → 合約範本。

  python3 -m marketing.team.kol_agent run --niche kingconn_b2b --seeds seeds.json --out DIR --top 10
  python3 -m marketing.team.kol_agent discover|score|brief|outreach|contract ... (分段)
  python3 -m marketing.team.kol_agent status          # cmo feed 用

抓取紀律:瀏覽器 UA、每次抓之前查該站 robots.txt、同站間隔 ≥2s、不登入、不帶 cookie、不繞驗證。
抓不到的指標一律 ❔(None),絕不寫 0 或「沒有」。
免費來源:YouTube 公開頻道頁/影片頁(不用 /results 搜尋,robots 禁)、Apple Podcasts 搜尋 API(免鑰匙)、RSS。
YouTube Data API 有 YT_API_KEY 時自動改走 API(search/channels/videos,每日 10,000 單位免費)。
LinkedIn / Threads / IG 公開頁有登入牆或 robots 拒 → 只吃 seeds 手列,指標 ❔。
⚠️ 只產草稿,不寄信、不留言、不私訊。
"""
import argparse
import html as htmlmod
import json
import re
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
NICHES = HERE / "kol_niches.json"
RATES = HERE / "kol_rates_tw.json"
TEMPLATES = HERE / "kol_templates"
STATE = HERE / "kol_state.json"
LEDGER = HERE / "kol_ledger.jsonl"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/128.0.0.0 Safari/537.36")
MIN_INTERVAL = 2.0
RECENT_N = 10
UNKNOWN = None  # 序列化成 null;報表印 ❔

BRAND_SAFETY_BASE = [
    "政治", "選舉", "統獨", "民進黨", "國民黨", "仇恨", "歧視", "色情", "成人", "賭博", "博弈", "詐騙", "詐欺",
    "毒品", "酒駕", "抄襲", "炎上", "翻車", "道歉聲明", "性騷", "霸凌", "爭議", "被告", "吸金", "投資保證",
    "scam", "gambling", "casino", "porn", "nsfw", "racist", "controversy", "lawsuit",
]


def q(s):
    return "❔" if s is None else s


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- fetcher
class Fetcher:
    def __init__(self, log_path=None, min_interval=MIN_INTERVAL, lang="en-US,en;q=0.9,zh-TW;q=0.8"):
        self.robots = {}
        self.last = {}
        self.log_path = log_path
        self.min_interval = min_interval
        self.lang = lang
        self.count = 0

    def _robots_ok(self, url):
        host = urllib.parse.urlsplit(url).netloc
        if host not in self.robots:
            rp = urllib.robotparser.RobotFileParser()
            try:
                self._wait(host)
                req = urllib.request.Request(f"https://{host}/robots.txt", headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=20) as r:
                    rp.parse(r.read().decode("utf-8", "replace").splitlines())
            except Exception:
                rp = None
            self.robots[host] = rp
        rp = self.robots[host]
        return True if rp is None else rp.can_fetch(UA, url)

    def _wait(self, host):
        t = self.last.get(host)
        if t is not None:
            d = time.time() - t
            if d < self.min_interval:
                time.sleep(self.min_interval - d)
        self.last[host] = time.time()

    def _log(self, rec):
        if self.log_path:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def get(self, url, accept="text/html"):
        host = urllib.parse.urlsplit(url).netloc
        rec = {"ts": now_iso(), "url": url}
        if not self._robots_ok(url):
            rec.update(status="ROBOTS_DISALLOW")
            self._log(rec)
            return None, "robots disallow"
        self._wait(host)
        t0 = time.time()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": self.lang, "Accept": accept + ",*/*;q=0.5"})
            with urllib.request.urlopen(req, timeout=30) as r:
                body = r.read().decode("utf-8", "replace")
                rec.update(status=r.status, bytes=len(body), ms=int((time.time() - t0) * 1000))
                self._log(rec)
                self.count += 1
                return body, None
        except urllib.error.HTTPError as e:
            rec.update(status=e.code, ms=int((time.time() - t0) * 1000))
            self._log(rec)
            return None, f"HTTP {e.code}"
        except Exception as e:
            rec.update(status="ERR", error=str(e)[:200])
            self._log(rec)
            return None, str(e)[:200]


# ---------------------------------------------------------------- parsing helpers
def _walk(o, key, acc):
    if isinstance(o, dict):
        for k, v in o.items():
            if k == key:
                acc.append(v)
            _walk(v, key, acc)
    elif isinstance(o, list):
        for v in o:
            _walk(v, key, acc)
    return acc


def _yt_initial(html_text, var="ytInitialData"):
    m = re.search(var + r"\s*=\s*(\{.*?\});\s*(?:</script>|var )", html_text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


_NUM = re.compile(r"([\d][\d,\.]*)\s*([KMB萬千億]?)")


def parse_count(text):
    """'2.16M subscribers' / '360K views' / '1.2萬' / '7,572' → int;抓不到 → None。"""
    if text is None:
        return None
    t = str(text).replace(" ", " ")
    m = _NUM.search(t)
    if not m:
        return None
    num = float(m.group(1).replace(",", ""))
    mult = {"K": 1e3, "M": 1e6, "B": 1e9, "千": 1e3, "萬": 1e4, "億": 1e8, "": 1}[m.group(2)]
    return int(num * mult)


def yt_base(ref):
    ref = ref.strip()
    if ref.startswith("http"):
        u = urllib.parse.urlsplit(ref)
        path = u.path.rstrip("/")
        for suffix in ("/videos", "/about", "/featured", "/shorts", "/streams"):
            if path.endswith(suffix):
                path = path[: -len(suffix)]
        return "https://www.youtube.com" + path
    if ref.startswith("@"):
        return "https://www.youtube.com/" + ref
    if ref.startswith("UC") and len(ref) == 24:
        return "https://www.youtube.com/channel/" + ref
    if ref.startswith(("c/", "channel/", "user/")):
        return "https://www.youtube.com/" + ref
    return "https://www.youtube.com/@" + ref


def yt_channel(fetcher, ref):
    """公開頻道頁 → 訂閱數、影片數、描述、近 N 支影片(id/標題/觀看/發布文字)。"""
    base = yt_base(ref)
    body, err = fetcher.get(base + "/videos")
    out = {"platform": "youtube", "url": base, "fetched_at": now_iso(), "subscribers": UNKNOWN, "video_count": UNKNOWN,
           "name": UNKNOWN, "handle": UNKNOWN, "description": "", "channel_id": UNKNOWN, "recent": [], "error": err}
    if body is None:
        return out
    d = _yt_initial(body)
    if not d:
        out["error"] = "ytInitialData 缺(頁面改版或被擋)"
        return out
    meta = _walk(d, "channelMetadataRenderer", [])
    if meta:
        m = meta[0]
        out["name"] = m.get("title")
        out["description"] = m.get("description") or ""
        out["channel_id"] = m.get("externalId")
        v = m.get("vanityChannelUrl") or ""
        out["handle"] = "@" + v.rsplit("@", 1)[-1] if "@" in v else UNKNOWN
        out["keywords"] = m.get("keywords") or ""
    hdr = json.dumps(_walk(d, "pageHeaderViewModel", []), ensure_ascii=False)
    for c in re.findall(r'"content":\s*"([^"]{0,80})"', hdr):
        low = c.lower()
        if "subscriber" in low or "訂閱者" in c or "位訂閱" in c:
            out["subscribers"] = parse_count(c)
        elif re.search(r"\bvideos?\b|部影片|支影片", low):
            out["video_count"] = parse_count(c)
    for l in _walk(d, "lockupViewModel", [])[:RECENT_N]:
        vid = l.get("contentId")
        md = (l.get("metadata") or {}).get("lockupMetadataViewModel") or {}
        title = ((md.get("title") or {}).get("content"))
        parts = []
        for row in ((md.get("metadata") or {}).get("contentMetadataViewModel") or {}).get("metadataRows", []):
            for p in row.get("metadataParts", []):
                parts.append(((p.get("text") or {}).get("content")) or "")
        views_txt = next((p for p in parts if "view" in p.lower() or "觀看" in p), None)
        when_txt = next((p for p in parts if "ago" in p.lower() or "前" in p), None)
        if vid:
            out["recent"].append({"video_id": vid, "url": f"https://www.youtube.com/watch?v={vid}", "title": title,
                                  "views": parse_count(views_txt), "published_text": when_txt,
                                  "likes": UNKNOWN, "comments": UNKNOWN, "published": UNKNOWN})
    return out


def yt_video_metrics(fetcher, v):
    body, err = fetcher.get(v["url"])
    if body is None:
        v["error"] = err
        return v
    m = re.search(r"like this video along with ([\d,]+) other people", body)
    if m:
        v["likes"] = int(m.group(1).replace(",", ""))
    else:
        m = re.search(r'"accessibilityText":"([\d,\.KM]+) likes?"', body)
        v["likes"] = parse_count(m.group(1)) if m else UNKNOWN
    d = _yt_initial(body)
    cc = _walk(d, "commentCount", []) if d else []
    txt = None
    for c in cc:
        if isinstance(c, dict):
            txt = c.get("simpleText") or "".join(r.get("text", "") for r in c.get("runs", []))
            if txt:
                break
    if not txt:
        m = re.search(r'"contextualInfo":\{"runs":\[\{"text":"([\d,\.KM]+)"\}\]\}', body)
        txt = m.group(1) if m else None
    if not txt:
        m = re.search(r'([\d,\.KM]+)\s+Comments', body)
        txt = m.group(1) if m else None
    v["comments"] = parse_count(txt) if txt else UNKNOWN
    pr = _yt_initial(body, "ytInitialPlayerResponse")
    if pr:
        vd = pr.get("videoDetails") or {}
        v["views"] = parse_count(vd.get("viewCount")) or v.get("views")
        v["length_s"] = parse_count(vd.get("lengthSeconds"))
        v["published"] = ((pr.get("microformat") or {}).get("playerMicroformatRenderer") or {}).get("publishDate")
        v["tags"] = (vd.get("keywords") or [])[:15]
    return v


def yt_api_available(env):
    return bool(env.get("YT_API_KEY"))


def podcasts_search(fetcher, term, country="tw", limit=10):
    u = "https://itunes.apple.com/search?" + urllib.parse.urlencode({"term": term, "country": country, "media": "podcast", "limit": limit})
    body, err = fetcher.get(u, accept="application/json")
    if body is None:
        return [], err
    try:
        res = json.loads(body).get("results", [])
    except json.JSONDecodeError:
        return [], "bad json"
    out = []
    for r in res:
        out.append({"platform": "podcast", "name": r.get("collectionName"), "handle": r.get("artistName"),
                    "url": r.get("collectionViewUrl"), "feed": r.get("feedUrl"), "episodes": r.get("trackCount"),
                    "genres": r.get("genres"), "subscribers": UNKNOWN, "recent": [], "description": "",
                    "fetched_at": now_iso(), "search_term": term})
    return out, None


def podcast_feed(fetcher, p):
    if not p.get("feed"):
        return p
    body, err = fetcher.get(p["feed"], accept="application/rss+xml")
    if body is None:
        p["error"] = err
        return p
    try:
        root = ET.fromstring(body.encode("utf-8"))
    except ET.ParseError:
        p["error"] = "rss parse"
        return p
    ch = root.find("channel")
    if ch is None:
        return p
    p["description"] = (ch.findtext("description") or "")[:1000]
    items = ch.findall("item")[:RECENT_N]
    for it in items:
        p["recent"].append({"title": it.findtext("title"), "published_text": it.findtext("pubDate"), "url": it.findtext("link"),
                            "views": UNKNOWN, "likes": UNKNOWN, "comments": UNKNOWN,
                            "description": (it.findtext("description") or "")[:300]})
    p["episodes"] = p.get("episodes") or len(ch.findall("item"))
    return p


# ---------------------------------------------------------------- scoring
def _days_since(text):
    """'2 weeks ago' / '3 個月前' / RFC822 / ISO → 天數;抓不到 None。"""
    if not text:
        return None
    t = str(text)
    m = re.search(r"(\d+)\s*(second|minute|hour|day|week|month|year)s?\s*ago", t)
    unit = {"second": 0, "minute": 0, "hour": 0, "day": 1, "week": 7, "month": 30, "year": 365}
    if m:
        return int(m.group(1)) * unit[m.group(2)]
    m = re.search(r"(\d+)\s*(秒|分鐘|小時|天|週|個月|年)前", t)
    unit2 = {"秒": 0, "分鐘": 0, "小時": 0, "天": 1, "週": 7, "個月": 30, "年": 365}
    if m:
        return int(m.group(1)) * unit2[m.group(2)]
    for fmt in ("%Y-%m-%d", "%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z"):
        try:
            dt = datetime.strptime(t[:31] if "%z" in fmt or "%Z" in fmt else t[:10], fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return (datetime.now(timezone.utc) - dt).days
        except ValueError:
            continue
    return None


def _median(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def relevance(c, keywords):
    """(0-30, hits)。近作標題各自比對(20)+ 頻道描述比對(10)。"""
    recent = c.get("recent") or []
    hits = {}
    per_video = 0
    for v in recent:
        text = (v.get("title") or "") + " " + " ".join(v.get("tags") or []) + " " + (v.get("description") or "")
        hit = False
        for kw, w in keywords.items():
            if kw.lower() in text.lower():
                hits[kw] = hits.get(kw, 0) + w
                hit = True
        per_video += 1 if hit else 0
    desc = (c.get("description") or "") + " " + (c.get("keywords") or "") + " " + (c.get("name") or "")
    desc_w = 0
    for kw, w in keywords.items():
        if kw.lower() in desc.lower():
            hits[kw] = hits.get(kw, 0) + w
            desc_w += w
    s_video = 20 * per_video / len(recent) if recent else 0
    s_desc = min(10, desc_w * 2.5)
    return round(s_video + s_desc, 1), sorted(hits.items(), key=lambda kv: -kv[1])[:8]


def engagement(c):
    recent = c.get("recent") or []
    ers = []
    for v in recent:
        if v.get("views") and v.get("likes") is not None:
            ers.append((v["likes"] + (v.get("comments") or 0)) / v["views"])
    er = _median(ers)
    if er is None:
        return None, None
    bands = [(0.05, 30), (0.03, 24), (0.02, 18), (0.01, 12), (0.005, 6)]
    score = next((s for th, s in bands if er >= th), 3)
    return score, round(er * 100, 2)


def size_fit(c, niche_id):
    subs = c.get("subscribers")
    if subs is None:
        return None
    band = (5000, 200000) if niche_id.endswith("b2b") else (10000, 500000)
    if band[0] <= subs <= band[1]:
        return 15
    if subs < band[0]:
        return 8 if subs >= 1000 else 3
    return 8 if subs <= band[1] * 5 else 3


def activity(c):
    ds = [_days_since(v.get("published") or v.get("published_text")) for v in (c.get("recent") or [])]
    ds = [d for d in ds if d is not None]
    if not ds:
        return None, None
    d = min(ds)
    return (10 if d <= 30 else 6 if d <= 90 else 3 if d <= 180 else 0), d


def fake_signals(c):
    """回 (0-15, flags)。純結構訊號:觀看/訂閱比、讚/觀看比、留言/讚比。留言重複度需留言全文(Data API commentThreads)→ ❔。"""
    flags = []
    score = 15
    subs = c.get("subscribers")
    recent = c.get("recent") or []
    views = _median([v.get("views") for v in recent])
    if subs and views is not None:
        r = views / subs
        if r < 0.005:
            score -= 8
            flags.append(f"觀看/訂閱比 {r:.2%} 過低(殭屍粉訊號)")
        elif r > 5:
            flags.append(f"觀看/訂閱比 {r:.0%} 異常高(爆紅或買量,需人工看)")
    lr = _median([v["likes"] / v["views"] for v in recent if v.get("views") and v.get("likes") is not None])
    if lr is not None and lr > 0.15:
        score -= 5
        flags.append(f"讚/觀看比 {lr:.1%} 異常高")
    cl = _median([v["comments"] / v["likes"] for v in recent if v.get("likes") and v.get("comments") is not None])
    if cl is not None and cl > 1:
        score -= 3
        flags.append(f"留言/讚比 {cl:.2f} > 1(刷留言訊號)")
    measurable = subs is not None or lr is not None
    return (max(0, score) if measurable else None), flags + ["留言重複度 ❔(需 YouTube Data API commentThreads)"]


def brand_safety(c, extra):
    words = BRAND_SAFETY_BASE + list(extra or [])
    texts = [(v.get("title") or "") + " " + (v.get("description") or "") for v in (c.get("recent") or [])] + [c.get("description") or ""]
    hits = []
    for t in texts:
        for w in words:
            if w.lower() in t.lower() and w not in hits:
                hits.append(w)
    return hits


def tier_of(subs, rates):
    if subs is None:
        return None
    for t in rates["tiers"]:
        if subs >= t["min"] and (t["max"] is None or subs < t["max"]):
            return t["id"]
    return None


def cpe_estimate(c, rates):
    """用行情帶 ÷ 近作中位互動 → CPE 帶。任何一端 ❔ 就 ❔。"""
    plat = c["platform"]
    key = {"youtube": "youtube_video", "instagram": "instagram_post", "threads": "threads_post",
           "podcast": "podcast_mention_30s", "linkedin": "linkedin_post"}.get(plat)
    band_def = rates["bands"].get(key) if key else None
    if not band_def:
        return {"price_band": None, "cpe_band": None, "basis": "❔ 平台無行情帶"}
    tier = tier_of(c.get("subscribers"), rates)
    band = band_def.get("any") or (band_def.get(tier) if tier else None)
    if not band:
        return {"price_band": None, "cpe_band": None, "tier": tier, "basis": f"❔ 行情帶缺({band_def.get('source', '')[:80]})"}
    eng = _median([(v.get("likes") or 0) + (v.get("comments") or 0) for v in (c.get("recent") or []) if v.get("likes") is not None])
    lo, hi = band
    out = {"price_band": [lo, hi], "tier": tier, "basis": band_def.get("source", "")[:160], "kind": band_def.get("kind")}
    if eng:
        out["median_engagements"] = int(eng)
        out["cpe_band"] = [round(lo / eng, 1), (round(hi / eng, 1) if hi else None)]
    else:
        out["cpe_band"] = None
        out["median_engagements"] = None
    return out


def score_candidate(c, niche, niche_id, rates):
    kw = niche["keywords"]
    rel, hits = relevance(c, kw)
    eng, er_pct = engagement(c)
    size = size_fit(c, niche_id)
    act, last_days = activity(c)
    fake, fflags = fake_signals(c)
    safety = brand_safety(c, niche.get("brand_safety_extra"))
    comps = {"relevance": (rel, 30), "engagement": (eng, 30), "size_fit": (size, 15), "activity": (act, 10), "authenticity": (fake, 15)}
    got = sum(v for v, _ in comps.values() if v is not None)
    maxp = sum(m for v, m in comps.values() if v is not None)
    total = round(100 * got / maxp, 1) if maxp else None
    if total is not None and safety:
        total = round(max(0, total - 10), 1)
    adjusted = round(total * (maxp / 100) ** 0.5, 1) if total is not None else None
    c["score"] = {"total": total, "adjusted": adjusted, "coverage": f"{maxp}/100",
                  "components": {k: v for k, (v, _) in comps.items()},
                  "engagement_rate_pct": er_pct, "keyword_hits": hits, "last_post_days": last_days,
                  "fake_flags": fflags, "brand_safety_hits": safety}
    c["cpe"] = cpe_estimate(c, rates)
    return c


# ---------------------------------------------------------------- pipeline
def load_niche(niche_id):
    data = json.loads(NICHES.read_text(encoding="utf-8"))
    if niche_id not in data["niches"]:
        raise SystemExit(f"利基 {niche_id} 不在 {NICHES}:{list(data['niches'])}")
    return data["niches"][niche_id]


def load_env():
    env = {}
    for p in (ROOT / "marketing" / ".env", ROOT / ".env"):
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    return env


def discover(niche_id, out, seeds_path=None, max_videos=RECENT_N, podcast_limit=6):
    niche = load_niche(niche_id)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    f = Fetcher(log_path=out / "fetch_log.jsonl")
    seeds = {"youtube": list(niche.get("youtube_seeds", [])), "podcast_terms": list(niche.get("podcast_terms", [])), "manual": []}
    if seeds_path:
        s = json.loads(Path(seeds_path).read_text(encoding="utf-8"))
        seeds["youtube"] += s.get("youtube", [])
        seeds["podcast_terms"] = s.get("podcast_terms", seeds["podcast_terms"])
        seeds["manual"] += s.get("manual", [])
    env = load_env()
    cands = []
    print(f"探索 {niche['name']}:YouTube 種子 {len(seeds['youtube'])} · Podcast 詞 {len(seeds['podcast_terms'])} · 手列 {len(seeds['manual'])}"
          f" · YouTube Data API {'有' if yt_api_available(env) else '無(走公開頁)'}")
    seen = set()
    for ref in seeds["youtube"]:
        c = yt_channel(f, ref)
        key = c.get("channel_id") or c["url"]
        if key in seen:
            continue
        seen.add(key)
        c["source"] = "youtube_public_page"
        for v in c["recent"][:max_videos]:
            yt_video_metrics(f, v)
        print(f"  YT {q(c.get('name')):<28} subs {q(c.get('subscribers'))!s:<9} 近作 {len(c['recent'])}  {c.get('error') or ''}")
        cands.append(c)
    for term in seeds["podcast_terms"]:
        res, err = podcasts_search(f, term, limit=podcast_limit)
        for p in res:
            if p["url"] in seen:
                continue
            seen.add(p["url"])
            p["source"] = "apple_podcasts_search"
            podcast_feed(f, p)
            print(f"  POD {q(p.get('name'))[:28]:<28} eps {q(p.get('episodes'))!s:<9} 近作 {len(p['recent'])}  {p.get('error') or ''}")
            cands.append(p)
    for m in seeds["manual"]:
        c = {"platform": m.get("platform", "manual"), "name": m.get("name"), "handle": m.get("handle"), "url": m.get("url"),
             "subscribers": m.get("followers"), "description": m.get("description", ""), "recent": [], "source": "manual_seed",
             "manual_note": m.get("note", "指標 ❔:平台有登入牆/robots 拒,只列不抓"), "fetched_at": now_iso()}
        cands.append(c)
    raw = {"niche": niche_id, "niche_name": niche["name"], "generated_at": now_iso(), "fetches": f.count,
           "fetch_policy": {"ua": "browser", "robots": "checked per host", "min_interval_s": MIN_INTERVAL, "login": False},
           "candidates": cands}
    (out / "raw_candidates.json").write_text(json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"→ {out / 'raw_candidates.json'}  候選 {len(cands)} · 抓取 {f.count} 次")
    return raw


def score(out):
    out = Path(out)
    raw = json.loads((out / "raw_candidates.json").read_text(encoding="utf-8"))
    niche = load_niche(raw["niche"])
    rates = json.loads(RATES.read_text(encoding="utf-8"))
    cands = [score_candidate(c, niche, raw["niche"], rates) for c in raw["candidates"]]
    cands.sort(key=lambda c: (-(c["score"]["adjusted"] if c["score"]["adjusted"] is not None else -1), c.get("name") or ""))
    for i, c in enumerate(cands, 1):
        c["rank"] = i
        c["slug"] = re.sub(r"[^a-z0-9]+", "_", (c.get("handle") or c.get("name") or f"kol{i}").lower()).strip("_") or f"kol{i}"
    raw["candidates"] = cands
    raw["scored_at"] = now_iso()
    raw["rates_collected_at"] = rates.get("collected_at")
    (out / "candidates.json").write_text(json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"評分完成 → {out / 'candidates.json'}")
    for c in cands:
        s = c["score"]
        print(f"  #{c['rank']:<2} {q(c.get('name'))[:26]:<26} {c['platform']:<8} 追蹤 {q(c.get('subscribers'))!s:<9} 分 {q(s['adjusted'])!s:<6}(量測 {q(s['total'])!s:<5}) "
              f"ER {q(s['engagement_rate_pct'])!s:<6} rel {s['components']['relevance']:<5} 覆蓋 {s['coverage']} {'⚠' + ','.join(s['brand_safety_hits']) if s['brand_safety_hits'] else ''}")
    return raw


def pick_format(niche, platform):
    fm = niche["collab_formats"]
    want = {"youtube": ("開箱", "影片"), "podcast": ("Podcast",), "linkedin": ("LinkedIn",), "instagram": ("Reels", "限動"), "threads": ("貼文",)}.get(platform, ())
    return next((x for x in fm if any(w in x for w in want)), fm[-1] if platform != "youtube" else fm[0])


def _clear(d, suffix=".md"):
    d.mkdir(exist_ok=True)
    for f in d.glob("*" + suffix):
        f.unlink()


def _fill(tpl, ctx):
    return re.sub(r"\{\{(\w+)\}\}", lambda m: str(ctx.get(m.group(1), "❔")), tpl)


def _fmt_band(b, unit="NT$"):
    if not b:
        return "❔"
    lo, hi = b
    return f"{unit}{lo:,.0f}–{hi:,.0f}" if hi is not None else f"{unit}{lo:,.0f}+"


def brief(out, top=10):
    out = Path(out)
    raw = json.loads((out / "candidates.json").read_text(encoding="utf-8"))
    niche = load_niche(raw["niche"])
    bdir = out / "briefs"
    _clear(bdir)
    rows = []
    for c in raw["candidates"][:top]:
        s = c["score"]
        cpe = c.get("cpe") or {}
        why = []
        if s["keyword_hits"]:
            why.append("主題命中:" + "、".join(k for k, _ in s["keyword_hits"][:5]))
        if s["engagement_rate_pct"] is not None:
            why.append(f"近作互動率 {s['engagement_rate_pct']}%(中位)")
        if s["last_post_days"] is not None:
            why.append(f"最近更新 {s['last_post_days']} 天前")
        if c.get("subscribers") is not None:
            why.append(f"追蹤 {c['subscribers']:,}(層級 {cpe.get('tier') or '❔'})")
        fmt = pick_format(niche, c["platform"])
        recent_md = "\n".join(f"| {q(v.get('title'))[:60]} | {q(v.get('views'))} | {q(v.get('likes'))} | {q(v.get('comments'))} | {q(v.get('published') or v.get('published_text'))} |"
                              for v in c.get("recent", [])[:RECENT_N]) or "| ❔ | | | | |"
        md = f"""# KOL 簡報 #{c['rank']}|{q(c.get('name'))}({c['platform']} {q(c.get('handle'))})

**利基:**{raw['niche_name']} · **品牌:**{niche.get('brand') or '❔'} · **來源:**{c.get('source')} · **抓取:**{c.get('fetched_at')}
**頁面:**{q(c.get('url'))}

## 為什麼是這位
{chr(10).join('- ' + w for w in why) or '- ❔(指標抓不到,只有名單)'}
{('- ⚠ 手列項:' + c['manual_note']) if c.get('manual_note') else ''}

## 分數 {q(s['adjusted'])} / 100(量測分 {q(s['total'])} × √覆蓋率 {s['coverage']};抓不到的維度不給分也不假設)
| 維度 | 分 | 滿分 |
|---|---|---|
| 主題相關度 | {q(s['components']['relevance'])} | 30 |
| 互動率 | {q(s['components']['engagement'])} | 30 |
| 規模適配 | {q(s['components']['size_fit'])} | 15 |
| 活躍度 | {q(s['components']['activity'])} | 10 |
| 真實性(假粉訊號) | {q(s['components']['authenticity'])} | 15 |

- 假粉訊號:{'; '.join(s['fake_flags'])}
- 品牌安全掃描:{('⚠ 命中 ' + '、'.join(s['brand_safety_hits']) + '(需人工看內容)') if s['brand_safety_hits'] else '近作標題/描述未命中爭議關鍵字(僅關鍵字掃描,非人工審)'}

## 預估 CPE
- 行情帶({cpe.get('kind') or '❔'}):{_fmt_band(cpe.get('price_band'))} / 每則
- 近作中位互動:{q(cpe.get('median_engagements'))}
- **CPE 帶:{_fmt_band(cpe.get('cpe_band'))} / 每互動**
- 依據:{cpe.get('basis') or '❔'}
- ⚠ 行情帶是代理商/比價網整理非平台正式報告;實際報價以創作者公開價或議定為準。

## 建議合作型式
{fmt}

## KPI 與歸屬
{niche.get('kpi_hint')}

## 近作(最多 {RECENT_N})
| 標題 | 觀看 | 讚 | 留言 | 發布 |
|---|---|---|---|---|
{recent_md}

## 揭露(必做)
公平會《網路廣告處理原則》(2023-02 修正納管網紅)與《薦證廣告規範說明》:合作/贈品/報酬關係要在內容顯眼處揭露;2024-09 首宗網紅團購案(Airvida)廣告主罰 50 萬、團購主各 5 萬(公處字第 113063 號)。合約範本見 contract_template.md。
"""
        (bdir / f"{c['rank']:02d}_{c['slug']}.md").write_text(md, encoding="utf-8")
        rows.append(f"| {c['rank']} | {q(c.get('name'))} | {c['platform']} | {q(c.get('subscribers'))} | {q(s['adjusted'])}({s['coverage']}) | {q(s['engagement_rate_pct'])} | "
                    f"{s['components']['relevance']} | {_fmt_band(cpe.get('cpe_band'))} | {'⚠' if s['brand_safety_hits'] else '—'} |")
    readme = f"""# KOL 候選簡報|{raw['niche_name']}

產生 {now_iso()} · 引擎 marketing/team/kol_agent.py · 抓取 {raw.get('fetches')} 次(瀏覽器 UA、逐站 robots、≥2s 間隔、未登入)
候選 {len(raw['candidates'])} 位,列前 {min(top, len(raw['candidates']))} 位;❔=抓不到,不是零。
**外聯草稿只產不寄;任何寄送需老闆核可。**

| # | 名稱 | 平台 | 追蹤數 | 分數(覆蓋) | 互動率% | 相關度/30 | CPE 帶 | 品牌安全 |
|---|---|---|---|---|---|---|---|---|
{chr(10).join(rows)}

- 分數=量測分 × √覆蓋率(覆蓋=有幾分可量;Podcast/LinkedIn 抓不到互動就只剩 40/100 可量,分數自動打折而不是假設它好);Podcast/LinkedIn 沒有公開互動數 ⇒ 互動率 ❔、分數只由相關度/活躍度撐。
- CPE 帶=行情帶 ÷ 近作中位互動;行情來源 marketing/team/kol_rates_tw.json(代理商/比價網整理,非平台正式報告)。
- 檔案:briefs/(每位一頁)、outreach/(中英開發信草稿)、contract_template.md(合約+揭露條款)、candidates.json(全資料)、fetch_log.jsonl(每次抓取)。
"""
    (out / "README.md").write_text(readme, encoding="utf-8")
    print(f"簡報 {min(top, len(raw['candidates']))} 份 → {bdir}/ 與 {out / 'README.md'}")


def outreach(out, top=10, brand=None, agency="QFX Solution", sender="Delvin", contact="❔"):
    out = Path(out)
    raw = json.loads((out / "candidates.json").read_text(encoding="utf-8"))
    niche = load_niche(raw["niche"])
    odir = out / "outreach"
    _clear(odir)
    tz = (TEMPLATES / "outreach_zh.md").read_text(encoding="utf-8")
    te = (TEMPLATES / "outreach_en.md").read_text(encoding="utf-8")
    tb = (TEMPLATES / "brief.md").read_text(encoding="utf-8")
    n = 0
    for c in raw["candidates"][:top]:
        s = c["score"]
        rv = next((v for v in c.get("recent", []) if v.get("title")), {})
        fmt = pick_format(niche, c["platform"])
        ctx = {
            "creator_name": q(c.get("name")), "platform": c["platform"], "handle": q(c.get("handle")),
            "brand": brand or niche.get("brand") or "❔", "agency": agency, "sender": sender, "contact": contact,
            "format": fmt, "format_short": fmt.split(":")[0][:12],
            "relevant_topic": q(rv.get("title")), "relevant_url": q(rv.get("url")),
            "why_you": ("您的內容剛好在講「" + "、".join(k for k, _ in s["keyword_hits"][:3]) + "」,和我們的產品線直接相關") if s["keyword_hits"] else "您的受眾正是我們想對話的工程師社群",
            "deliverable_from_brand": "樣品(免費,不計入報酬)、型錄與交叉料號表、工程師一對一技術支援",
            "payment_terms": "簽約付 50%、上線後 50%",
            "deliverables": "1 支影片(≥8 分鐘)+ 資訊欄連結 + 1 則社群貼文", "window": "❔(議定)", "must_say": "產品型號、規格以書面為準",
            "slug": c["slug"], "campaign": raw["niche"], "code": "❔", "kpi": niche.get("kpi_hint"), "license_months": 12,
        }
        (odir / f"{c['rank']:02d}_{c['slug']}_zh.md").write_text(_fill(tz, ctx), encoding="utf-8")
        (odir / f"{c['rank']:02d}_{c['slug']}_en.md").write_text(_fill(te, ctx), encoding="utf-8")
        (odir / f"{c['rank']:02d}_{c['slug']}_brief.md").write_text(_fill(tb, ctx), encoding="utf-8")
        n += 1
    print(f"外聯草稿 {n} 位 × (zh/en/brief) → {odir}/  【只產不寄】")


def contract(out, brand=None, agency="QFX Solution"):
    out = Path(out)
    raw = json.loads((out / "candidates.json").read_text(encoding="utf-8"))
    niche = load_niche(raw["niche"])
    t = (TEMPLATES / "contract_disclosure.md").read_text(encoding="utf-8")
    ctx = {"brand": brand or niche.get("brand") or "❔", "agency": agency, "creator_name": "{{creator_name}}", "platform": "{{platform}}",
           "handle": "{{handle}}", "format": "{{format}}", "deliverables": "{{deliverables}}", "window": "{{window}}", "fee": "{{fee}}",
           "samples": "{{samples}}", "payment_terms": "簽約付 50%、上線並確認揭露合規後付 50%", "license_months": 12, "retain_months": 12,
           "court": "臺灣桃園"}
    (out / "contract_template.md").write_text(_fill(t, ctx), encoding="utf-8")
    print(f"合約+揭露條款範本 → {out / 'contract_template.md'}")


def write_state(out, raw):
    out = Path(out)
    top = [{"rank": c["rank"], "name": c.get("name"), "platform": c["platform"], "subscribers": c.get("subscribers"), "score": c["score"]["adjusted"]}
           for c in raw["candidates"][:10]]
    st = {"last_run": now_iso(), "niche": raw["niche"], "out": str(out), "candidates": len(raw["candidates"]), "fetches": raw.get("fetches"), "top": top}
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    with open(LEDGER, "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": st["last_run"], "niche": st["niche"], "candidates": st["candidates"], "out": st["out"]}, ensure_ascii=False) + "\n")


def status():
    if not STATE.exists():
        print("KOL 席:尚未跑過")
        return 1
    st = json.loads(STATE.read_text(encoding="utf-8"))
    age = (datetime.now(timezone.utc) - datetime.strptime(st["last_run"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)).total_seconds() / 3600
    print(f"KOL 席:上次 {st['last_run']}({age:.1f}h 前)利基 {st['niche']} 候選 {st['candidates']} → {st['out']}")
    for t in st["top"][:5]:
        print(f"  #{t['rank']} {q(t['name'])} {t['platform']} 追蹤 {q(t['subscribers'])} 分 {q(t['score'])}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["run", "discover", "score", "brief", "outreach", "contract", "status"])
    ap.add_argument("--niche", default="kingconn_b2b")
    ap.add_argument("--seeds")
    ap.add_argument("--out")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--brand")
    ap.add_argument("--agency", default="QFX Solution")
    ap.add_argument("--contact", default="❔")
    ap.add_argument("--max-videos", type=int, default=RECENT_N)
    a = ap.parse_args(argv)
    if a.cmd == "status":
        return status()
    if not a.out:
        ap.error("--out 必填")
    if a.cmd in ("run", "discover"):
        discover(a.niche, a.out, a.seeds, a.max_videos)
    if a.cmd in ("run", "score"):
        raw = score(a.out)
    if a.cmd in ("run", "brief"):
        brief(a.out, a.top)
    if a.cmd in ("run", "outreach"):
        outreach(a.out, a.top, a.brand, a.agency, contact=a.contact)
    if a.cmd in ("run", "contract"):
        contract(a.out, a.brand, a.agency)
    if a.cmd == "run":
        write_state(a.out, raw)
    return 0


if __name__ == "__main__":
    sys.exit(main())
