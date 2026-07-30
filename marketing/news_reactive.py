#!/usr/bin/env python3
"""新聞快評自動發文線 —— 重大財經新聞 → 個股技術面快照 → AI 文案 → IG/FB/Threads 直發。

流程(單次呼叫走完,fail-closed,任一閘不過=當輪不發):
  ①scan:cnyes(tw_stock/us_stock/wd_stock/headline,即時) + NewsAPI 美股補掃(免費層有~24h延遲,
    只當 backstop) → 事件關鍵字分級 × 大型權值股名單比對 → 計分取最高、seen ledger 去重
  ②enrich:Yahoo chart 抓該個股日K → 確定性算 RSI14/MA20/MA50/5日%/量能比(數字全在 Python 算,
    LLM 只准引用,不准自產——feedback_digest_content 進出場價教訓)
  ③draft:headless claude 產 caption_zh + card_headline(strict JSON)
  ④gate:確定性閘(禁詞/必含網址/「caption 每個數字必在 FACTS 內」數字回驗)
  ⑤verify:全新 context headless claude 獨立驗證者逐項裁決(marketing-verify 慣例,缺席=駁回)
  ⑥publish:social_cards 圖卡 → JPG → KV(media.marketdaily.ai) → 直發(冪等靠 auto_post LOG_FILE)

合規(marketing/CLAUDE.md 新聞hook軌):外部新聞數字必帶 source_url;我方產品數據(勝率/訂戶)絕不出現;
不含買賣建議價位字眼(2026-06-02 明牌教訓);個股分析永不與付費掛鉤。

用法:
  python3 -m marketing.news_reactive scan            # 只看候選排序,不發
  python3 -m marketing.news_reactive run --dry       # 走完 draft+verify,印 caption,不發
  python3 -m marketing.news_reactive run             # 全流程直發(cron 用;窗口/每日鎖在 runner)
  python3 -m marketing.news_reactive run --force     # 略過每日上限/間隔(手動救援用)
"""
import datetime
import hashlib
import json
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))

from auto_post import (LOG_FILE, PLATFORMS, _png_to_jpg_playwright,  # noqa: E402
                       caption_for, load_env)
from daily_run import posted_ids  # noqa: E402
from social_cards import make_card  # noqa: E402

STATE_FILE = HERE / "social_out" / "news_reactive_state.json"
PNG_DIR = HERE / "assets" / "posts" / "news"
KV_NAMESPACE = "9f3b5e510de04803bd0b59d451911d58"
MEDIA_BASE = "https://media.marketdaily.ai"
SITE_URL = "https://marketdaily.ai/?utm_source=social&utm_medium=post&utm_campaign=news_reactive"
POST_PLATFORMS = ["instagram", "facebook", "threads"]
DAILY_CAP = 3
MIN_GAP_MIN = 120
FRESH_HOURS = 14          # cnyes 即時源只看這麼新的
SWEEP_HOURS = 36          # NewsAPI backstop(免費層延遲,分數自帶衰減)
UA = "Mozilla/5.0"

# (ticker, market us/tw, yahoo symbol, 顯示名, [比對別名 zh/en 小寫])
COMPANIES = [
    ("NVDA", "us", "NVDA", "輝達 NVIDIA", ["輝達", "nvidia", "黃仁勳"]),
    ("2330", "tw", "2330.TW", "台積電", ["台積電", "tsmc"]),
    ("AMD", "us", "AMD", "超微 AMD", ["超微", " amd", "amd "]),
    ("INTC", "us", "INTC", "英特爾 Intel", ["英特爾", "intel"]),
    ("TSLA", "us", "TSLA", "特斯拉 Tesla", ["特斯拉", "tesla", "馬斯克"]),
    ("GOOGL", "us", "GOOGL", "Alphabet", ["alphabet", "谷歌", "google"]),
    ("AAPL", "us", "AAPL", "蘋果 Apple", ["蘋果", "apple", "庫克"]),
    ("MSFT", "us", "MSFT", "微軟 Microsoft", ["微軟", "microsoft"]),
    ("META", "us", "META", "Meta", ["meta", "祖克柏", "臉書"]),
    ("AMZN", "us", "AMZN", "亞馬遜 Amazon", ["亞馬遜", "amazon"]),
    ("AVGO", "us", "AVGO", "博通 Broadcom", ["博通", "broadcom"]),
    ("MU", "us", "MU", "美光 Micron", ["美光", "micron"]),
    ("2317", "tw", "2317.TW", "鴻海", ["鴻海", "foxconn"]),
    ("3231", "tw", "3231.TW", "緯創", ["緯創", "wistron"]),
    ("2382", "tw", "2382.TW", "廣達", ["廣達", "quanta"]),
    ("2308", "tw", "2308.TW", "台達電", ["台達電"]),
    ("3661", "tw", "3661.TW", "世芯-KY", ["世芯"]),
    ("2454", "tw", "2454.TW", "聯發科", ["聯發科", "mediatek"]),
]

# (type, zh標籤, 權重, kw_en, kw_zh) —— 貼文價值導向,跟 intel/news_signals 的風險分級是兩套目的
EVENT_TYPES = [
    ("invest_mna", "投資/併購", 5,
     ["acquire", "acquisition", "merger", "stake", "invests", "investment in", "buyout"],
     ["收購", "併購", "入股", "投資", "合併", "注資"]),
    ("earnings", "財報/財測", 4,
     ["earnings", "guidance", "beats", "misses", "revenue", "forecast"],
     ["財報", "財測", "營收", "獲利", "超預期", "不如預期", "展望"]),
    ("product_launch", "產品/量產", 4,
     ["launch", "unveil", "mass production", "production", "new chip", "platform"],
     ["量產", "發表", "發布", "新品", "晶片", "平台", "開幕"]),
    ("partnership", "合作/訂單", 4,
     ["partnership", "deal", "contract", "supply", "order", "partners"],
     ["合作", "結盟", "簽約", "訂單", "供貨", "夥伴", "打入"]),
    ("regulatory", "監管/風險", 3,
     ["antitrust", "probe", "investigation", "lawsuit", "fined", "recall"],
     ["反壟斷", "調查", "訴訟", "罰款", "召回", "禁令"]),
    ("big_move", "股價異動", 3,
     ["surges", "plunges", "soars", "tumbles", "record high", "sell-off"],
     ["暴漲", "暴跌", "飆", "重挫", "創新高", "崩", "反彈"]),
]


def _utcnow():
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


def _tw_today():
    return (_utcnow() + datetime.timedelta(hours=8)).strftime("%Y-%m-%d")


def _fetch(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _classify(title):
    low = title.lower()
    best = None
    for typ, zh, w, kw_en, kw_zh in EVENT_TYPES:
        if any(k in low for k in kw_en) or any(k in title for k in kw_zh):
            if best is None or w > best[2]:
                best = (typ, zh, w)
    return best


def _match_company(title):
    low = title.lower()
    for tick, mkt, ysym, disp, aliases in COMPANIES:
        if any(a in low if a.isascii() else a in title for a in aliases):
            return {"ticker": tick, "market": mkt, "yahoo": ysym, "name": disp}
    return None


def fetch_candidates():
    """回打分排序的候選 [{title,url,date,age_h,company,etype,etype_zh,score,key}]。"""
    arts = []
    cutoff = _utcnow() - datetime.timedelta(hours=FRESH_HOURS)
    seen_titles = set()
    for cat in ("tw_stock", "us_stock", "wd_stock", "headline"):
        try:
            data = json.loads(_fetch(
                f"https://news.cnyes.com/api/v3/news/category/{cat}?limit=30", timeout=15))
        except Exception:
            continue
        for item in data.get("items", {}).get("data", []):
            title = (item.get("title") or "").strip()
            if not title or title in seen_titles:
                continue
            seen_titles.add(title)
            ts = item.get("publishAt", 0)
            d = datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).replace(tzinfo=None) if ts else None
            if not d or d < cutoff:
                continue
            nid = item.get("newsId", "")
            arts.append({"title": title, "date": d,
                         "url": f"https://news.cnyes.com/news/id/{nid}" if nid else "https://news.cnyes.com"})
    try:
        from intel.news_signals import _fetch_us_articles
        for a in _fetch_us_articles(SWEEP_HOURS):
            if a["title"] not in seen_titles:
                seen_titles.add(a["title"])
                arts.append(a)
    except Exception:
        pass

    out = []
    now = _utcnow()
    for a in arts:
        cls = _classify(a["title"])
        comp = _match_company(a["title"])
        if not cls or not comp:
            continue
        typ, zh, w = cls
        age_h = max(0.0, (now - a["date"]).total_seconds() / 3600)
        score = w + (3 if age_h <= 3 else (1 if age_h <= 8 else 0)) - (2 if age_h > 20 else 0)
        if comp["ticker"] in ("NVDA", "2330", "TSLA", "AAPL", "MSFT", "GOOGL"):
            score += 2
        out.append({**a, "age_h": round(age_h, 1), "company": comp,
                    "etype": typ, "etype_zh": zh, "score": score,
                    "key": hashlib.sha1(a["title"].encode()).hexdigest()[:16]})
    out.sort(key=lambda c: (-c["score"], c["age_h"]))
    return out


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"seen": {}, "posted": []}


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    cut = (_utcnow() - datetime.timedelta(days=14)).strftime("%Y-%m-%d")
    state["seen"] = {k: v for k, v in state["seen"].items() if v >= cut}
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


def pick(state, cands):
    today = _tw_today()
    pair_recent = {(p["ticker"], p.get("etype")) for p in state["posted"]
                   if p["date"] >= (_utcnow() - datetime.timedelta(days=2)).strftime("%Y-%m-%d")}
    for c in cands:
        if c["key"] in state["seen"]:
            continue
        if (c["company"]["ticker"], c["etype"]) in pair_recent:
            continue
        if c["score"] < 6:      # 水位:平庸新聞不值得發,寧缺勿濫
            continue
        return c
    return None


def tech_snapshot(ysym):
    """Yahoo chart 6mo 日K → 確定性技術面快照(全部先格式化成字串,LLM 只准照抄)。
    注意 reference_yahoo_chart_gotcha:不用 chartPreviousClose,一律從 closes 序列自算。"""
    try:
        data = json.loads(_fetch(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{ysym}?range=6mo&interval=1d",
            timeout=20))
        res = data["chart"]["result"][0]
        q = res["indicators"]["quote"][0]
        closes = [c for c in q["close"] if c is not None]
        vols = [v for v in (q.get("volume") or []) if v is not None]
        if len(closes) < 55:
            return None
    except Exception:
        return None
    last = closes[-1]
    ma20 = sum(closes[-20:]) / 20
    ma50 = sum(closes[-50:]) / 50
    chg1 = (last / closes[-2] - 1) * 100
    chg5 = (last / closes[-6] - 1) * 100
    deltas = [closes[i] - closes[i - 1] for i in range(len(closes) - 14, len(closes))]
    gain = sum(d for d in deltas if d > 0) / 14
    loss = -sum(d for d in deltas if d < 0) / 14
    rsi = 100.0 if loss == 0 else 100 - 100 / (1 + gain / loss)
    hi20 = max(closes[-20:])
    volx = (vols[-1] / (sum(vols[-21:-1]) / 20)) if len(vols) >= 21 and sum(vols[-21:-1]) else None
    fmt = lambda v, n=1: f"{v:.{n}f}"
    snap = {
        "收盤價": fmt(last, 2 if last < 1000 else 0),
        "當日漲跌%": ("+" if chg1 >= 0 else "") + fmt(chg1),
        "5日漲跌%": ("+" if chg5 >= 0 else "") + fmt(chg5),
        "RSI14": fmt(rsi),
        "距MA20%": ("+" if last >= ma20 else "") + fmt((last / ma20 - 1) * 100),
        "距MA50%": ("+" if last >= ma50 else "") + fmt((last / ma50 - 1) * 100),
        "距20日高點%": fmt((last / hi20 - 1) * 100),
    }
    if volx:
        snap["量能比20日均"] = fmt(volx) + "x"
    return snap


def source_excerpt(url, limit=1200):
    """best-effort 抓來源內文(給 LLM 更多真材料+給驗證者對照);抓不到就退回標題-only。"""
    try:
        html = _fetch(url, timeout=15).decode("utf-8", "ignore")
        html = re.sub(r"(?is)<(script|style|nav|header|footer)[^>]*>.*?</\1>", " ", html)
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text).strip()
        m = re.search(r"[一-鿿]", text)
        if m:
            text = text[m.start():]
        return text[:limit] if len(text) > 200 else None
    except Exception:
        return None


def build_facts(cand, tech, excerpt):
    return {
        "news_headline": cand["title"],
        "news_source_url": cand["url"],
        "news_published_utc": cand["date"].strftime("%Y-%m-%d %H:%M"),
        "event_type": cand["etype_zh"],
        "company": cand["company"]["name"],
        "ticker": cand["company"]["ticker"],
        "market": "台股" if cand["company"]["market"] == "tw" else "美股",
        "tech_snapshot": tech,
        "source_excerpt": excerpt,
        "site_url": SITE_URL,
        "today_tw": _tw_today(),
    }


DRAFT_PROMPT = """<role>
You are the social media editor for MarketDaily (marketdaily.ai), a Traditional-Chinese daily
finance AI newsletter for Taiwan investors. Voice: sharp, insider, data-grounded, zero hype.
</role>

<context>
MarketDaily is currently fully free (limited-time early-bird: subscribe now, keep free access
forever). Its edge: daily personalized stock reports with technical + institutional signals.
This post is a breaking-news quick take ("新聞快評") that shows readers analysis they cannot
get from the headline alone, then invites them to the site.
</context>

<task>
Write ONE Instagram/Facebook/Threads caption in Traditional Chinese (zh-TW) reacting to the
news in <facts>, plus a short image-card headline. Structure of caption, in order:
1. Hook line about the news (no clickbait lies).
2. What happened: 1-2 sentences of facts, mention the news is from the linked source.
3. 個股技術面快照: interpret 2-4 numbers from tech_snapshot for THIS stock (RSI, vs MA20/50,
   volume). Plain-language reading, e.g. whether momentum is stretched or basing.
4. 「MarketDaily 觀點」paragraph: our view AND the reasoning why, hedged (我們認為/傾向/
   要留意), strictly observational — never instructions to buy or sell.
5. One line about the offer, phrased about the PLATFORM as a whole, e.g.
   MarketDaily 全功能目前限時免費開放,早鳥訂閱者永久保留免費使用權.
   CRITICAL: never attach 限時免費/早鳥/免費期 wording to 個股分析/持股報告/分析內容
   itself — stock analysis is free forever by law; only the platform/full-feature offer
   may be described as limited-time free.
6. CTA line containing the exact URL from site_url.
7. 3-5 hashtags in Chinese, none containing digits.
Also produce caption_threads_zh: a standalone condensed version for Threads (hard API
limit 500 chars total): hook + core fact + ONE technical or viewpoint line + the exact
site_url + at most 2 hashtags. Max 360 Chinese characters BEFORE the URL. Same rules.
In BOTH captions the offer line must stand alone as its own complete sentence. NEVER merge
限時免費/早鳥 wording into the same clause as 分析/完整分析/報告/解讀/持股 (e.g.
「全功能限時免費,完整分析 →」is a hard compliance violation). If the Threads version is
tight on space, DROP the offer line entirely rather than compressing it into the CTA.
When citing the source, name it (e.g. 據鉅亨網報導); never write 連結/link about the
source since no source link is attached to the post.
</task>

<constraints>
1. Caption 350-900 Chinese characters total (excluding URL and hashtags).
2. EVERY digit sequence in caption and card_headline MUST appear verbatim somewhere in
   <facts> (headline, tech_snapshot values, source_excerpt, dates). Never compute, round,
   or invent numbers. If a number you want is not in <facts>, write without it.
3. FORBIDDEN words/ideas: 買進,買入,賣出,進場,出場,停損,停利,目標價,加碼,減碼,抄底,上車,
   梭哈,保證,穩賺,必漲,必跌,翻倍,勝率,訂戶數/用戶數 claims,付費,Pro方案,LINE.
   No promises of returns. No claim that analysis is or will be paid.
4. Must contain the exact string of site_url once, in the CTA line.
5. If tech_snapshot is null, skip section 3's numbers and write a qualitative line instead.
6. Do not translate company names oddly; use the name given in <facts>.
7. card_headline: max 16 Chinese characters, punchy, factual, no digits unless in <facts>.
8. Traditional Chinese (zh-TW) characters ONLY, in every field. Never emit Simplified forms
   (亚这两个们时说对现实发产业经济资报导观软数变电华应场关开门问间车东马头银长国图 …).
   Mixed Simplified/Traditional output is an automatic reject.
</constraints>

<output_format>
Reply with STRICT JSON only, no markdown fences, exactly:
{"caption_zh": "...", "caption_threads_zh": "...", "card_headline": "..."}
Example shape (placeholder text, do not reuse its wording):
{"caption_zh": "輝達又出手了…(全文)…完整分析 → https://example…\\n\\n#美股 #AI", "caption_threads_zh": "輝達又出手了…(短版)… https://example… #美股", "card_headline": "輝達出手投資雲端新星"}
</output_format>

<facts>
{FACTS}
</facts>"""

VERIFY_PROMPT = """<role>
You are an independent, adversarial fact-check auditor for MarketDaily's social posts.
You did NOT write this caption. Default to REJECT when uncertain.
</role>

<task>
Audit the caption+card_headline in <draft> against <facts>. Check every item:
1. Every digit sequence in the draft appears verbatim in <facts>. List any that do not.
2. Every factual claim is traceable to <facts> (headline/excerpt/tech_snapshot). No invented
   events, quotes, amounts, or dates.
3. None of these appear: 買進,買入,賣出,進場,出場,停損,停利,目標價,加碼,減碼,抄底,上車,梭哈,
   保證,穩賺,必漲,必跌,翻倍,勝率 claims,訂戶/用戶數 claims,付費,Pro方案,LINE.
4. Contains the exact site_url string from <facts>.
5. No promise of investment returns; viewpoint is hedged and observational.
6. Compliance. The platform-level offer sentence approved by the owner (2026-07-09 口徑),
   e.g. 「MarketDaily 全功能目前限時免費開放,早鳥訂閱者永久保留免費使用權」, is PRE-CLEARED —
   do NOT flag it merely because it follows the analysis paragraph. Fail check 6 ONLY when
   限時免費/早鳥/免費期/解鎖 wording directly modifies 個股分析/持股報告/分析內容 itself
   (e.g.「個股分析限時免費」「早鳥才看得到完整分析」), or when the draft otherwise states
   or implies stock analysis is or will be paid, gated, or tiered.
7. Natural fluent zh-TW; no broken half-sentences; hashtags have no digits.
</task>

<output_format>
STRICT JSON only: {"pass": true|false, "violations": ["..."]}
pass=true ONLY if all 7 checks pass.
</output_format>

<facts>
{FACTS}
</facts>

<draft>
{DRAFT}
</draft>"""


# 明確指定模型鏈(2026-07-30 Delvin 親令「這種都用 opus 就好」):不吃 CLI 預設(=Fable 5,
# 週額度見底就整條線失敗刷屏),第一順位固定 opus,後面兩個只是保命降級。
CLAUDE_MODEL_CHAIN = ["opus", "sonnet", "haiku"]
_QUOTA_RE = re.compile(r"reached your .{0,40}limit|usage-credits|usage limit|rate.?limit", re.I)


class ClaudeQuotaExhausted(RuntimeError):
    """claude CLI 額度耗盡(429)——基礎設施狀態,不是這則新聞的問題,不標 seen。"""


def _claude_once(prompt, timeout_s, model=None):
    cmd = ["claude", "-p", prompt, "--dangerously-skip-permissions", "--output-format", "json"]
    if model:
        cmd[1:1] = ["--model", model]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)
    raw = r.stdout or ""
    try:
        payload = json.loads(raw)
    except Exception:
        payload = None
    tag = model or "default"
    # CLI 有時 rc=0 仍把 429 包在 result 裡,兩條路徑都要判成額度耗盡
    if payload is not None:
        result_txt = str(payload.get("result", ""))
        if payload.get("api_error_status") == 429 or _QUOTA_RE.search(result_txt):
            raise ClaudeQuotaExhausted(f"{tag}: {result_txt[:140]}")
    if r.returncode != 0:
        err = (r.stderr or raw)[-300:]
        if _QUOTA_RE.search(err):
            raise ClaudeQuotaExhausted(f"{tag}: {err[-140:]}")
        raise RuntimeError(f"claude rc={r.returncode} (model={tag}): {err}")
    body = (payload if payload is not None else json.loads(raw))["result"]
    body = re.sub(r"^```(json)?|```$", "", body.strip(), flags=re.M).strip()
    start, end = body.find("{"), body.rfind("}")
    if start < 0 or end < 0:
        raise ValueError(f"no JSON in claude output: {body[:200]}")
    return json.loads(body[start:end + 1])


def call_claude(prompt, timeout_s):
    """opus 額度滿才依序降級;全滿才拋 ClaudeQuotaExhausted(單一則告警)。"""
    errs = []
    for model in CLAUDE_MODEL_CHAIN:
        try:
            return _claude_once(prompt, timeout_s, model)
        except ClaudeQuotaExhausted as e:
            errs.append(str(e))
            print(f"  ⚠ 額度耗盡({model or 'default'}),降級下一個模型")
    raise ClaudeQuotaExhausted("所有模型額度皆耗盡:" + " | ".join(errs))


FORBIDDEN = ["買進", "買入", "賣出", "進場", "出場", "停損", "停利", "目標價", "加碼", "減碼",
             "抄底", "上車", "梭哈", "全倉", "掛單", "挂單", "保證", "穩賺", "必漲", "必跌",
             "翻倍", "財富自由", "勝率", "訂戶", "訂閱人數", "萬用戶", "位用戶", "付費",
             "Pro方案", "LINE", "解鎖"]


def _digits_in(obj, acc):
    if obj is None:
        return acc
    if isinstance(obj, dict):
        for k, v in obj.items():
            _digits_in(k, acc)   # key 也收:RSI14/距MA20% 這類指標名的數字是合法引用
            _digits_in(v, acc)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _digits_in(v, acc)
    else:
        for m in re.findall(r"\d+(?:\.\d+)?", str(obj)):
            acc.add(m.lstrip("0") or "0")
            acc.add(m)
    return acc


# 只在簡體中文出現、正體中文絕不會用的字(刻意排除 後/裡/幹/只/面/制/強/戶/著 這類兩岸皆用的)
SIMPLIFIED_ONLY = set(
    "亚产亿仅从价众优传伤体债内军农冲决况净减击则刚创别办务动医华协单卖卫却厂历压县参双"
    "叶号员响团园圆圣场坏块坚执声处备复够夹奋娱孙宁宝实审层属岁岛币师带帮广庆库废异张弹"
    "归当录忆态总恋恶惊惯愿战扑扩扫扬担拟择挂据换摄摆敌数断无旧显术机杀杂权条来极构枪栏"
    "树桥检楼标欢欧残毁汇汉沟泪洁济测浓涛润渐湾满滨灭灯灵灾炉点烦热爱爷独环电画畅疗盘盖"
    "监码确碍础礼祸离种积称稳竞笔筑简签类紧级纪纳纵纷纸线组细织终绍经结给络绝统继绩续维"
    "编缩网罗罚义习联肠肤胜胶脉脏脑脸腾舰艰节苏苹药荐荣获莱营蓝虑补装见观规视览觉誉计订"
    "认讨让训议讯记讲许论设访证评识诉诊词译试诗诚话详语误说请读课谁调谈谋谓谢谱变财责贤"
    "败货质贩贪贫购贯贷贸费贺贴贵贼资赋赌赏赔赖赚赛赞赠赢赶趋跃转轮软轰轻载较辅辆辈输辑"
    "辞边达迁过运还这进远违连迟适选递逻遗邓郑释钟钢钱钻铁铃银铺链销锁锋锐错锦键镇镜长门"
    "闭问闲间闻阁阅阴队阶际陆陈险隐难雾韩页顶项顺须预领频题颜额风飞饭饮饰饱馆马驶驻驾验"
    "骗骤鱼鲁鲜鸟鸡鸣鹤麦"
)


def caption_gate(caption, threads_caption, headline, facts):
    """確定性閘:LLM prompt 永遠不是唯一防線(feedback_zero_error_no_miss)。回 violations list。"""
    v = []
    text = caption + "\n" + (threads_caption or "") + "\n" + headline
    # 合規鐵則(COMPLIANCE_STRUCTURE.md):個股分析依法永遠免費,免費/早鳥字眼只能修飾「平台」。
    # 同一子句內同時出現優惠字與分析字 = 暗示分析被收費或設限,確定性擋掉,不靠 LLM 驗證者。
    for seg in re.split(r"[。;;!!??\n]", text):
        if any(w in seg for w in ("限時免費", "早鳥", "免費期", "解鎖")) and \
           any(w in seg for w in ("分析", "報告", "解讀", "持股", "選股")):
            v.append(f"合規:優惠字眼與分析內容同句({seg.strip()[:40]})")
            break
    zh_bad = sorted({c for c in text if c in SIMPLIFIED_ONLY})
    if zh_bad:
        v.append("簡體字(全文必須 zh-TW 正體):" + "".join(zh_bad[:10]))
    for w in FORBIDDEN:
        if w in text:
            v.append(f"禁詞:{w}")
    if SITE_URL not in caption:
        v.append("缺 site_url(必須一字不差含 UTM)")
    allowed = _digits_in(facts, set())
    for num in re.findall(r"\d+(?:\.\d+)?", text.replace(SITE_URL, "")):
        if num not in allowed and (num.lstrip("0") or "0") not in allowed:
            v.append(f"數字不在FACTS內:{num}")
    body_len = len(re.sub(r"https?://\S+|#\S+", "", caption))
    if not 200 <= body_len <= 1100:
        v.append(f"長度異常:{body_len}")
    if len(re.findall(r"#\S+", caption)) > 6:
        v.append("hashtag 過多")
    if threads_caption:
        if SITE_URL not in threads_caption:
            v.append("threads 版缺 site_url")
        if len(threads_caption) > 495:
            v.append(f"threads 版超長:{len(threads_caption)}(API上限500)")
    else:
        v.append("缺 caption_threads_zh")
    return v


def render_news_card(cand, tech, headline_zh, out_png):
    comp = cand["company"]
    body = [f"{comp['name']}({comp['ticker']}) · {cand['etype_zh']}"]
    if tech:
        body.append(f"收盤 {tech['收盤價']}({tech['當日漲跌%']}%) · 5日 {tech['5日漲跌%']}%")
        line3 = f"RSI14 {tech['RSI14']} · 距MA20 {tech['距MA20%']}%"
        if tech.get("量能比20日均"):
            line3 += f" · 量能 {tech['量能比20日均']}"
        body.append(line3)
    body.append("來源:" + ("鉅亨網" if "cnyes" in cand["url"] else "外電"))
    spec = {"tag": f"新聞快評 · {_tw_today()}", "headline": headline_zh,
            "body": "\n".join(body), "cta": "完整個股分析 marketdaily.ai →"}
    make_card(spec, out_png)
    return out_png


def upload_media(jpg, key):
    """wrangler kv put + HEAD 驗檔(照 video_brief/make_post.py 慣例:rc 只當參考,成敗看 HEAD)。"""
    url = f"{MEDIA_BASE}/{key}"
    size = jpg.stat().st_size
    for attempt in range(1, 4):
        r = subprocess.run(
            ["npx", "wrangler", "kv", "key", "put", key, "--path", str(jpg),
             "--namespace-id", KV_NAMESPACE, "--remote"],
            capture_output=True, text=True, cwd=ROOT)
        if r.returncode == 0:
            break
        print(f"  ⚠ wrangler put rc={r.returncode} ({attempt}/3)")
        time.sleep(5)
    for _ in range(6):
        time.sleep(8)
        try:
            req = urllib.request.Request(url, method="HEAD",
                                         headers={"User-Agent": "MarketDailyBot/1.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                if int(resp.headers.get("content-length", 0)) == size:
                    return url
        except Exception:
            pass
    raise RuntimeError(f"上傳後 {url} 驗不到正確檔案")


def post_direct(env, post_id, image_url, caption, threads_caption=None):
    """直發(不入 social_posts.json 品牌佇列——兩條內容流分開);冪等靠 LOG_FILE。
    Threads API 上限 500 字 → 用 draft 一起產出並過同一套閘門的短版。"""
    results = {}
    print(f"發布 [{post_id}] → {image_url}")
    for plat in POST_PLATFORMS:
        fn = PLATFORMS[plat]
        text = threads_caption if (plat == "threads" and threads_caption) else caption
        try:
            ok, detail = fn(env, image_url, caption_for(text, plat))
        except KeyError as e:
            ok, detail = False, f".env 缺少 {e}"
        results[plat] = {"ok": ok, "detail": str(detail)}
        print(f"  {'✅' if ok else '❌'} {plat}: {detail}")
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": datetime.datetime.now().isoformat(), "post": post_id,
                            "results": results}, ensure_ascii=False) + "\n")
    return results


def cmd_scan():
    cands = fetch_candidates()
    state = load_state()
    print(f"候選 {len(cands)} 則(門檻分=6):")
    for c in cands[:10]:
        mark = "seen" if c["key"] in state["seen"] else ""
        print(f"  [{c['score']:>2}] {c['age_h']:>4}h {c['company']['ticker']:<6} "
              f"{c['etype_zh']:<6} {c['title'][:52]} {mark}")
    chosen = pick(state, cands)
    print(f"\n本輪會選:{chosen['title'][:60] if chosen else '(無達標候選)'}")


def retry_failed(state):
    """同日貼文的平台級失敗自動補發(首日 Threads 500字失敗靠人工補的教訓)。
    每平台最多重試 2 次;重試耗盡仍失敗 → 回 rc=1 讓 runner 的 cron_run_and_alert 推 admin。"""
    today = _tw_today()
    rc = 0
    env = None
    for entry in state["posted"]:
        if entry["date"] != today or "results" not in entry:
            continue
        for plat, r in entry["results"].items():
            if r.get("ok") or r.get("retries", 0) >= 2 or r.get("exhausted"):
                continue
            env = env or load_env()
            text = entry.get("threads_caption") if plat == "threads" and entry.get("threads_caption") \
                else entry.get("caption", "")
            if not text or not entry.get("image_url"):
                r["exhausted"] = True   # 舊 schema 沒存文案,無從重試
                continue
            print(f"重試 {entry['id']} → {plat} (第{r.get('retries', 0) + 1}次)")
            try:
                ok, detail = PLATFORMS[plat](env, entry["image_url"], caption_for(text, plat))
            except Exception as e:
                ok, detail = False, str(e)
            r["retries"] = r.get("retries", 0) + 1
            r["ok"], r["detail"] = bool(ok), str(detail)[:200]
            print(f"  {'✅' if ok else '❌'} {plat}: {str(detail)[:120]}")
            if not ok and r["retries"] >= 2:
                r["exhausted"] = True
                print(f"  ⚠ {plat} 重試耗盡,交給 runner 告警")
                rc = 1
    if env is not None:
        save_state(state)
    return rc


REJECT_ALERT_AFTER = 3   # 草稿被擋是把關成功,不是事故;連續這麼多次才當系統性品質問題告警


def _reject(state, cand, today, dry, retry_rc, who):
    """內容被閘門/驗證者擋下:標 seen 不重試,累計連續次數,連續超標才回 rc=1 觸發告警。"""
    if dry:
        return 1
    state["seen"][cand["key"]] = today   # 這則今天別再重試燒額度
    n = state.get("reject_streak", 0) + 1
    state["reject_streak"] = n
    save_state(state)
    if n < REJECT_ALERT_AFTER:
        print(f"({who}擋下=把關正常運作,連續第 {n}/{REJECT_ALERT_AFTER} 次,不告警)")
        return retry_rc
    print(f"⚠ 連續 {n} 次草稿被{who}擋下,升級告警(疑似系統性品質問題)")
    return 1


def cmd_run(dry=False, force=False):
    state = load_state()
    today = _tw_today()
    retry_rc = 0 if dry else retry_failed(state)
    todays = [p for p in state["posted"] if p["date"] == today]
    if not force:
        if len(todays) >= DAILY_CAP:
            print(f"今日已發 {len(todays)}/{DAILY_CAP},收工。")
            return retry_rc
        if state["posted"]:
            last_ts = state["posted"][-1].get("ts", 0)
            gap = (time.time() - last_ts) / 60
            if gap < MIN_GAP_MIN:
                print(f"距上一篇僅 {gap:.0f} 分(<{MIN_GAP_MIN}),下輪再說。")
                return retry_rc
    cands = fetch_candidates()
    cand = pick(state, cands)
    if not cand:
        print("無達標新聞候選,本輪不發。")
        return retry_rc
    comp = cand["company"]
    print(f"選中:[{cand['score']}] {cand['title']}\n  → {comp['name']} {cand['url']}")

    tech = tech_snapshot(comp["yahoo"])
    if tech:
        print(f"  技術面:{tech}")
    else:
        print("  ⚠ 技術面抓取失敗,走 qualitative 路徑")
    excerpt = source_excerpt(cand["url"])
    facts = build_facts(cand, tech, excerpt)
    facts_json = json.dumps(facts, ensure_ascii=False, indent=1)

    draft = call_claude(DRAFT_PROMPT.replace("{FACTS}", facts_json), 300)
    caption, headline = draft["caption_zh"], draft["card_headline"]
    threads_caption = draft.get("caption_threads_zh", "")
    print(f"\n--- caption ---\n{caption}\n--- threads({len(threads_caption)}字) ---\n{threads_caption}\n--- card: {headline} ---\n")

    gate_v = caption_gate(caption, threads_caption, headline, facts)
    if gate_v:
        print(f"❌ 確定性閘未過:{gate_v}")
        return _reject(state, cand, today, dry, retry_rc, "確定性閘")
    verdict = call_claude(
        VERIFY_PROMPT.replace("{FACTS}", facts_json).replace("{DRAFT}", json.dumps(draft, ensure_ascii=False)), 240)
    if not verdict.get("pass"):
        print(f"❌ 獨立驗證者駁回:{verdict.get('violations')}")
        return _reject(state, cand, today, dry, retry_rc, "獨立驗證者")
    print("✅ 確定性閘+獨立驗證者全過")

    if dry:
        print("[dry] 不發文、不記 state。")
        return 0

    post_id = f"newsr_{today.replace('-', '')}_{comp['ticker'].lower()}"
    if post_id in posted_ids():
        print(f"{post_id} 已發過(LOG_FILE),跳過。")
        state["seen"][cand["key"]] = today
        save_state(state)
        return 0
    PNG_DIR.mkdir(parents=True, exist_ok=True)
    png = PNG_DIR / f"{post_id}.png"
    jpg = PNG_DIR / f"{post_id}.jpg"
    render_news_card(cand, tech, headline, png)
    _png_to_jpg_playwright(png, jpg)
    image_url = upload_media(jpg, f"social/{post_id}.jpg")
    env = load_env()
    results = post_direct(env, post_id, image_url, caption, threads_caption)
    ok_n = sum(1 for r in results.values() if r["ok"])
    state["seen"][cand["key"]] = today
    state["reject_streak"] = 0
    if ok_n:
        state["posted"].append({"date": today, "ts": time.time(), "id": post_id,
                                "ticker": comp["ticker"], "etype": cand["etype"],
                                "title": cand["title"][:80],
                                "image_url": image_url, "caption": caption,
                                "threads_caption": threads_caption,
                                "results": {p: {"ok": r["ok"], "detail": r["detail"][:200]}
                                            for p, r in results.items()}})
    save_state(state)
    print(f"完成:{ok_n}/{len(POST_PLATFORMS)} 平台成功。")
    return (0 if ok_n else 1) or retry_rc


def main():
    args = sys.argv[1:]
    if not args or args[0] == "scan":
        cmd_scan()
        return 0
    if args[0] == "run":
        try:
            return cmd_run(dry="--dry" in args, force="--force" in args)
        except ClaudeQuotaExhausted as e:
            # 額度是基礎設施狀態:留一行乾淨訊息給 runner 告警,不吐整串 traceback
            print(f"❌ claude 額度耗盡,本輪放棄(不標 seen,額度恢復後自動重試):{e}")
            return 1
    print(__doc__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
