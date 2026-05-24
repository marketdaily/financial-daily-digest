#!/usr/bin/env python3
"""
SEO 個股長尾文章自動生成 pipeline
- 每次跑生 5 篇 (default),配合 GitHub Actions weekly cron
- 用 Claude haiku 寫,每篇 ~800-1200 字
- 鎖長尾關鍵字:「<個股名> <主題> 2026」例如「台積電 2330 配息 2026」
- 輸出到 docs/blog/<slug>.html(自包含 HTML 含 MarketDaily 設計系統)
- 自動更新 docs/blog/index.html 列表
- sitemap.xml 自動 append 新文章

用法:
  python scripts/seo_articles.py                 # 預設生 5 篇
  python scripts/seo_articles.py --count 10      # 改 10 篇
  python scripts/seo_articles.py --dry           # 只 print 不寫檔
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY")
MODEL = "claude-haiku-4-5-20251001"

BLOG_DIR = ROOT / "docs" / "blog"
BLOG_DIR.mkdir(parents=True, exist_ok=True)
SEEDS_FILE = ROOT / "scripts" / "seo_seeds.json"

# 種子主題池 — 每篇文章從這拼湊長尾關鍵字
US_STOCKS = [
    ("NVDA", "輝達"), ("AAPL", "蘋果"), ("TSM", "台積電 ADR"),
    ("MSFT", "微軟"), ("META", "Meta"), ("GOOGL", "Google"),
    ("AMZN", "亞馬遜"), ("TSLA", "特斯拉"), ("AMD", "AMD"),
    ("NFLX", "Netflix"), ("AVGO", "博通"), ("PLTR", "Palantir"),
    ("COIN", "Coinbase"), ("UBER", "Uber"), ("DIS", "迪士尼"),
]
TW_STOCKS = [
    ("2330", "台積電"), ("2454", "聯發科"), ("2317", "鴻海"),
    ("2891", "中信金"), ("2882", "國泰金"), ("0050", "元大台灣50"),
    ("0056", "元大高股息"), ("00878", "國泰永續高股息"),
    ("2603", "長榮"), ("2308", "台達電"), ("3034", "聯詠"),
    ("2412", "中華電"), ("8299", "群聯"), ("3008", "大立光"),
]
TOPICS = [
    "投資前必看 3 個風險",
    "本益比合理嗎",
    "配息政策解析",
    "2026 展望",
    "競爭優勢與護城河",
    "近期財報重點",
    "適合長期持有嗎",
    "技術面 vs 基本面",
    "vs 同業比較",
    "新手第一次買要注意什麼",
]


def slug_of(ticker: str, topic: str) -> str:
    safe = re.sub(r"[^\w一-鿿]+", "-", topic)[:30]
    return f"{ticker.lower()}-{safe}-{datetime.now():%Y%m}"


def load_published() -> set:
    """掃 docs/blog/ 內已存在 slug,避免重複生。"""
    return {f.stem for f in BLOG_DIR.glob("*.html") if f.stem != "index"}


def call_claude(system: str, user: str, max_tokens: int = 2000) -> str:
    import urllib.request
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps({
            "model": MODEL,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }).encode(),
        headers={
            "x-api-key": ANTHROPIC_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.loads(r.read())
    return "".join(c.get("text", "") for c in data.get("content", [])).strip()


SYSTEM = """你是 MarketDaily 的財經 SEO 內容寫手。寫繁體中文 SEO 長尾文章。

規則:
- 800-1200 字
- 結構:H1 標題、引言(問題切入)、H2 分段(3-5 個)、結論 + CTA(訂閱 MarketDaily 早報)
- 開頭 80 字內必須出現關鍵字 + 數字(SEO bonus)
- 內容要有實質資訊,不空泛
- **不能保證收益、不能喊進喊出**(改寫成「值得關注」「需評估個人風險」)
- 結尾 CTA:「想每天早上 7 點收到這類分析?免費訂閱 MarketDaily → marketdaily.ai」
- 輸出純 HTML body 片段(從 <h1> 到結尾 </p>),不要 <html>/<head>/<body> 包裝
- HTML 用簡潔語意標籤:h1, h2, h3, p, ul, ol, strong
- 不寫日期(會過時),用「2026」這種年度即可"""


def gen_article(ticker: str, name: str, topic: str, market: str) -> dict:
    user = f"""寫一篇 SEO 文章。

關鍵字組合:「{name} {ticker} {topic}」
市場:{market}(美股/台股)

請按 SEO 結構寫,涵蓋 H1/H2/H3,800-1200 字,結尾接 CTA。

回傳純 HTML 片段(<h1>...到最後</p>),其他不要。"""
    body = call_claude(SYSTEM, user, max_tokens=3000)
    # 從 body 抽 H1 當 title
    m = re.search(r"<h1[^>]*>(.+?)</h1>", body, re.DOTALL)
    title = re.sub(r"<[^>]+>", "", m.group(1)).strip() if m else f"{name} {topic}"
    return {
        "ticker": ticker,
        "name": name,
        "topic": topic,
        "market": market,
        "title": title,
        "body_html": body,
        "slug": slug_of(ticker, topic),
    }


PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} | MarketDaily</title>
<meta name="description" content="{desc}">
<meta name="facebook-domain-verification" content="ylg7ynhyj5ywyoierjgo7mchqdvbek" />
<meta property="og:title" content="{title}">
<meta property="og:description" content="{desc}">
<meta property="og:type" content="article">
<meta property="og:url" content="https://marketdaily.ai/blog/{slug}.html">
<link rel="canonical" href="https://marketdaily.ai/blog/{slug}.html">
<style>
:root {{ color-scheme: dark; }}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ background:#0a0a14; color:#e2e8f0; font-family:'Inter','PingFang TC',sans-serif; line-height:1.75; }}
.wrap {{ max-width:720px; margin:0 auto; padding:48px 24px 80px; }}
.topnav {{ position:sticky; top:0; background:rgba(10,10,20,0.85); backdrop-filter:blur(12px); border-bottom:1px solid rgba(255,255,255,0.08); padding:14px 24px; display:flex; justify-content:space-between; align-items:center; z-index:10; }}
.topnav a {{ color:#a5b4fc; text-decoration:none; font-weight:700; }}
.crumb {{ font-size:13px; color:rgba(255,255,255,0.5); margin-bottom:12px; letter-spacing:0.5px; text-transform:uppercase; }}
h1 {{ font-size:36px; font-weight:900; color:#fff; margin:6px 0 24px; letter-spacing:-0.5px; }}
h2 {{ font-size:24px; font-weight:800; color:#fff; margin:36px 0 14px; }}
h3 {{ font-size:18px; font-weight:700; color:#c7d2fe; margin:24px 0 10px; }}
p {{ font-size:16px; color:#cbd5e1; margin:0 0 16px; }}
ul, ol {{ margin:12px 0 20px 24px; }}
li {{ font-size:16px; color:#cbd5e1; margin:8px 0; }}
strong {{ color:#fbbf24; font-weight:700; }}
.cta {{ background:linear-gradient(135deg,rgba(99,102,241,0.15),rgba(168,85,247,0.15)); border:1px solid rgba(99,102,241,0.35); border-radius:14px; padding:24px; margin:40px 0 0; text-align:center; }}
.cta a {{ display:inline-block; margin-top:14px; padding:14px 28px; background:linear-gradient(135deg,#6366f1,#a855f7); color:#fff; font-weight:800; text-decoration:none; border-radius:10px; }}
.disc {{ font-size:12px; color:rgba(255,255,255,0.4); margin-top:32px; padding-top:16px; border-top:1px solid rgba(255,255,255,0.08); }}
</style>
</head>
<body>
<div class="topnav">
  <a href="/">MarketDaily ←</a>
  <a href="/blog/index.html">所有文章</a>
</div>
<article class="wrap">
  <div class="crumb">MARKETDAILY · 個股分析 · {market_label}</div>
  {body}
  <div class="cta">
    <p style="font-size:18px;color:#fff;font-weight:800;margin:0;">想每天早上 7 點收到這類分析?</p>
    <p style="font-size:14px;color:rgba(255,255,255,0.65);margin:6px 0 0;">免費訂閱 MarketDaily — 美股 + 台股 AI 過濾日報,30 秒讀完。</p>
    <a href="https://marketdaily.ai/?utm_source=blog&utm_medium=cta&utm_campaign=seo_{slug_short}">免費訂閱 →</a>
  </div>
  <p class="disc">本文僅供資訊整理,非投資建議。投資有風險,請評估自身狀況。資料更新:{updated}</p>
</article>
</body>
</html>"""


def write_article(art: dict, dry: bool) -> Path:
    slug = art["slug"]
    fname = BLOG_DIR / f"{slug}.html"
    desc = f"{art['name']} ({art['ticker']}) {art['topic']} — MarketDaily 整理。"
    html = PAGE_TEMPLATE.format(
        title=art["title"],
        desc=desc,
        slug=slug,
        slug_short=slug[:32],
        market_label="美股" if art["market"] == "us" else "台股",
        body=art["body_html"],
        updated=datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d"),
    )
    if dry:
        print(f"  [dry] {fname.name}({len(html)} bytes)")
        return fname
    fname.write_text(html, encoding="utf-8")
    print(f"  ✓ {fname.name}")
    return fname


def regenerate_blog_index(dry: bool):
    """掃 docs/blog/ 所有文章,生成 index.html 列表頁。"""
    files = sorted(BLOG_DIR.glob("*.html"), key=lambda f: f.stat().st_mtime, reverse=True)
    files = [f for f in files if f.stem != "index"]
    items = []
    for f in files:
        try:
            m = re.search(r"<title>(.+?)\s*\|", f.read_text(encoding="utf-8"))
            title = m.group(1) if m else f.stem
        except Exception:
            title = f.stem
        items.append({"slug": f.stem, "title": title})

    cards = "\n".join(
        f'<a class="card" href="{it["slug"]}.html"><div class="card-title">{it["title"]}</div>'
        f'<div class="card-meta">→ 閱讀</div></a>'
        for it in items
    ) or '<p style="color:rgba(255,255,255,0.5)">尚無文章。</p>'

    idx_html = f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>個股分析文章 | MarketDaily</title>
<meta name="description" content="MarketDaily 個股深度分析,涵蓋美股、台股長尾關鍵字。">
<meta name="facebook-domain-verification" content="ylg7ynhyj5ywyoierjgo7mchqdvbek" />
<link rel="canonical" href="https://marketdaily.ai/blog/index.html">
<style>
:root {{ color-scheme: dark; }}
* {{ box-sizing:border-box; margin:0; padding:0; }}
body {{ background:#0a0a14; color:#e2e8f0; font-family:'Inter','PingFang TC',sans-serif; }}
.wrap {{ max-width:880px; margin:0 auto; padding:48px 24px 80px; }}
.topnav {{ padding:14px 24px; display:flex; justify-content:space-between; border-bottom:1px solid rgba(255,255,255,0.08); }}
.topnav a {{ color:#a5b4fc; text-decoration:none; font-weight:700; }}
h1 {{ font-size:32px; font-weight:900; color:#fff; margin-bottom:32px; }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(280px,1fr)); gap:16px; }}
.card {{ display:block; padding:20px; background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.08); border-radius:14px; text-decoration:none; color:inherit; transition:all 0.15s; }}
.card:hover {{ background:rgba(99,102,241,0.10); border-color:rgba(99,102,241,0.40); transform:translateY(-2px); }}
.card-title {{ font-size:16px; font-weight:700; color:#fff; line-height:1.5; }}
.card-meta {{ font-size:13px; color:#a5b4fc; margin-top:10px; }}
</style>
</head>
<body>
<div class="topnav">
  <a href="/">← MarketDaily</a>
  <a href="/pricing.html">定價</a>
</div>
<div class="wrap">
  <h1>個股分析 · {len(items)} 篇</h1>
  <div class="grid">{cards}</div>
</div>
</body>
</html>"""
    out = BLOG_DIR / "index.html"
    if dry:
        print(f"  [dry] index({len(items)} items)")
    else:
        out.write_text(idx_html, encoding="utf-8")
        print(f"  ✓ index.html ({len(items)} items)")


def pick_seeds(count: int, published: set) -> list:
    """從 stocks × topics 配對,挑沒寫過的 N 個。"""
    import random
    rng = random.Random(int(datetime.now().timestamp()))
    combos = []
    for code, name in US_STOCKS:
        for topic in TOPICS:
            combos.append((code, name, topic, "us"))
    for code, name in TW_STOCKS:
        for topic in TOPICS:
            combos.append((code, name, topic, "tw"))
    rng.shuffle(combos)
    picked = []
    for code, name, topic, market in combos:
        slug = slug_of(code, topic)
        if slug in published:
            continue
        picked.append((code, name, topic, market))
        if len(picked) >= count:
            break
    return picked


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=5)
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    if not ANTHROPIC_KEY and not args.dry:
        print("✗ ANTHROPIC_API_KEY missing in .env"); sys.exit(1)

    published = load_published()
    print(f"① 已發布 {len(published)} 篇,挑新主題 ×{args.count}...")
    seeds = pick_seeds(args.count, published)
    if not seeds:
        print("  全部 stocks×topics 組合都發過了,沒新主題可挑。"); return
    print("② 生成中...")
    for code, name, topic, market in seeds:
        print(f"  • {market.upper()} {code} {name} — {topic}")
        try:
            art = gen_article(code, name, topic, market)
            write_article(art, args.dry)
        except Exception as e:
            print(f"    ✗ failed: {e}")
    print("③ 更新 blog index...")
    regenerate_blog_index(args.dry)
    print("✓ done")


if __name__ == "__main__":
    main()
