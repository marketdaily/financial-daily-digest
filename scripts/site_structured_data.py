#!/usr/bin/env python3
"""
補齊 marketdaily.ai 兩類頁面缺少的 canonical + JSON-LD 結構化資料(SEO 成長線,
project_growth_channel_deep_dive_20260705 缺口②):

1. 頂層行銷頁(CORE,見 gen_sitemap.CORE,排除已有結構化資料的 / 與另一套 pipeline 的 /blog/):
   pricing/track-record/vs-chatgpt/vs/guide/about/contact/testimonials — 目前
   canonical=0、JSON-LD=0(唯讀稽核發現,首頁 index.html 是唯一有 @graph 的非 blog 頁)。
2. 日報公版 archive 長尾頁(docs/output/digest_*.html,gen_sitemap 收錄、逐日累加,
   目前 40+ 篇)——
   同樣 canonical=0、JSON-LD=0、meta description=0。description 從頁面自身
   「☕ 30 秒看完今天重點」TL;DR 條列文字抽取(零捏造,複用 seo_articles._truncate_to_desc
   同一套截斷邏輯),過濾 AI 生成異常的備援錯誤訊息開頭(不把系統性故障字句曝在公開 SERP)。

刻意不碰 main.py::render_email_shell(email 發送路徑,golden byte-frozen test 保護)——
只對「已寫出的靜態檔案」做 post-processing,兩者完全解耦,對日報寄送零影響。

冪等設計:注入的區塊包在具名 HTML 註解 marker(<!-- site_structured_data:start/end -->)
之間。每次執行都先剝掉舊區塊、重新算一次,若結果與現有內容位元相同則不寫檔——這樣
「已有 marker 就整篇跳過」不會把舊版邏輯的輸出永久凍結:修好抽取/跳脫邏輯後重跑本
腳本,既有頁面會自動更新成新結果,不需要額外的 force/overwrite flag。

用法:
  python scripts/site_structured_data.py --core --dry      # 預覽頂層頁改動
  python scripts/site_structured_data.py --core             # 真寫入頂層頁
  python scripts/site_structured_data.py --archive --dry    # 預覽 archive 頁改動
  python scripts/site_structured_data.py --archive          # 真寫入 archive 頁(冪等,只補缺的/更新變動的)
  python scripts/site_structured_data.py --all              # 兩者都做
"""
import argparse
import json
import re
import sys
from html import escape as _esc, unescape as _unesc
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from seo_articles import _truncate_to_desc  # noqa: E402  單一句界截斷邏輯來源

DOCS = ROOT / "docs"
BASE = "https://marketdaily.ai"
OG_IMAGE = "https://marketdaily.ai/assets/og.png"
LOGO = "https://marketdaily.ai/logo-icon.svg"
PUBLISHER = {"@type": "Organization", "name": "MarketDaily", "logo": {"@type": "ImageObject", "url": LOGO}}

MARKER_START = "<!-- site_structured_data:start -->"
MARKER_END = "<!-- site_structured_data:end -->"
_BLOCK_RE = re.compile(re.escape(MARKER_START) + r".*?" + re.escape(MARKER_END) + r"\n?", re.S)


def _strip_existing_block(html: str) -> str:
    """移除先前執行留下的注入區塊,讓每次重跑都是從『無本腳本痕跡』的乾淨狀態重算。"""
    return _BLOCK_RE.sub("", html)


def _wrap_block(lines: list) -> str:
    return MARKER_START + "\n" + "\n".join(lines) + "\n" + MARKER_END


# 與 gen_sitemap.py CORE 同一份清單(路徑→檔名),排除 "/"(已有 @graph)與 "/blog/"(獨立 pipeline)。
CORE_PAGES = {
    "/pricing": "pricing.html",
    "/track-record": "track-record.html",
    "/vs-chatgpt": "vs-chatgpt.html",
    "/vs": "vs.html",
    "/guide": "guide.html",
    "/about": "about.html",
    "/contact": "contact.html",
    "/testimonials": "testimonials.html",
}

# 僅少數頁完全無 meta description 可重用(og:description 也沒有),提供零捏造 fallback
# (從頁面自身真實文字內容手動摘要,非生成/推測)。
DESC_FALLBACK = {
    "/contact": "MarketDaily 聯絡我們:填寫表單由 AI 客服回覆到你的 Email,常見問題涵蓋日報發送時間、退訂方式與個人化內容說明。",
}

TITLE_RE = re.compile(r"<title>([^<]*)</title>")
META_DESC_RE = re.compile(r'<meta\s+name="description"\s+content="([^"]*)"\s*/?>')
OG_DESC_RE = re.compile(r'<meta\s+property="og:description"\s+content="([^"]*)"\s*/?>')
OG_URL_RE = re.compile(r'<meta\s+property="og:url"\s+content="[^"]*"\s*/?>')


def _webpage_schema_json(title: str, desc: str, url: str) -> str:
    node = {
        "@type": "WebPage",
        "name": title,
        "description": desc,
        "url": url,
        "image": OG_IMAGE,
        "publisher": PUBLISHER,
    }
    schema = {"@context": "https://schema.org", "@graph": [node]}
    return json.dumps(schema, ensure_ascii=False).replace("</", "<\\/")


def inject_core_page(path: str, fname: str, dry: bool) -> bool:
    """回傳是否有改動。冪等:剝掉舊區塊重算,結果不變就不寫檔。"""
    fpath = DOCS / fname
    original = fpath.read_text(encoding="utf-8")
    html = _strip_existing_block(original)
    url = f"{BASE}{path}"
    title_m = TITLE_RE.search(html)
    if not title_m:
        raise ValueError(f"{fname}: 找不到 <title> 標籤,無法插入結構化資料區塊,需人工檢查頁面結構")
    # 捕獲值來自既有 <title>/<meta content> 屬性,若原頁面本就用 HTML 實體寫特殊字元
    # (例如 &amp;),要先 unescape 回明文,才能對 HTML 屬性槽與 JSON-LD 槽各自正確跳脫一次
    # ——否則 HTML 槽會雙重跳脫(&amp;amp;)、JSON-LD 槽會殘留實體字面文字。
    title = _unesc(title_m.group(1))
    desc_m = META_DESC_RE.search(html) or OG_DESC_RE.search(html)
    desc = _unesc(desc_m.group(1)) if desc_m else DESC_FALLBACK.get(path, "")
    if not desc:
        raise ValueError(f"{fname}: 無 meta/og description 可重用,也無 fallback,需人工補")

    # HTML 屬性槽一律 html.escape(quote=True);JSON-LD 槽用未跳脫的原始 title/desc(json.dumps
    # 自己正確處理 " 跳脫,& < > 在 JSON 字串內是字面字元,不需要 HTML 實體)。
    title_a, desc_a = _esc(title, quote=True), _esc(desc, quote=True)
    block_lines = []
    if not META_DESC_RE.search(html):
        block_lines.append(f'<meta name="description" content="{desc_a}">')
    block_lines.append(f'<link rel="canonical" href="{url}">')
    if not OG_URL_RE.search(html):
        block_lines.extend([
            '<meta property="og:type" content="website">',
            '<meta property="og:site_name" content="MarketDaily">',
            f'<meta property="og:title" content="{title_a}">',
            f'<meta property="og:description" content="{desc_a}">',
            f'<meta property="og:url" content="{url}">',
            f'<meta property="og:image" content="{OG_IMAGE}">',
            '<meta property="og:image:width" content="1200">',
            '<meta property="og:image:height" content="630">',
            '<meta name="twitter:card" content="summary_large_image">',
            f'<meta name="twitter:title" content="{title_a}">',
            f'<meta name="twitter:description" content="{desc_a}">',
            f'<meta name="twitter:image" content="{OG_IMAGE}">',
        ])
    schema_json = _webpage_schema_json(title, desc, url)
    block_lines.append(f'<script type="application/ld+json">{schema_json}</script>')

    new_html = TITLE_RE.sub(lambda m: m.group(0) + "\n" + _wrap_block(block_lines), html, count=1)

    if new_html == original:
        return False
    if dry:
        print(f"  [dry] {fname}: would update")
    else:
        fpath.write_text(new_html, encoding="utf-8")
        print(f"  [applied] {fname}")
    return True


def backfill_core(dry: bool) -> list:
    changed = []
    for path, fname in CORE_PAGES.items():
        if inject_core_page(path, fname, dry):
            changed.append(fname)
    return changed


# ── 日報公版 archive 長尾頁 ──
DATE_RE = re.compile(r"digest_(\d{4}-\d{2}-\d{2})\.html$")
DIGEST_TITLE_RE = re.compile(r"<title>[^<]*</title>")
# div/ul 允許額外屬性(如 style=""/class=""),避免漏抓真實有 TL;DR 內容但 markup 稍有差異的舊版本頁面。
TLDR_RE = re.compile(r'<div class="tldr"[^>]*>.*?<ul[^>]*>(.*?)</ul>', re.S)
LI_RE = re.compile(r"<li[^>]*>(.*?)</li>", re.S)
_AI_FALLBACK_MARK = "⚠️ 今天 AI 個人化生成異常"


def _extract_tldr_text(html: str) -> str:
    """抽『☕ 30 秒看完今天重點』TL;DR 條列文字,過濾 AI 生成異常的系統性錯誤訊息
    (該訊息只是備援版本的操作提示,不是市場內容,不該曝在公開 SERP 摘要)。"""
    m = TLDR_RE.search(html)
    if not m:
        return ""
    parts = []
    for li in LI_RE.findall(m.group(1)):
        t = re.sub(r"<[^>]+>", "", li)
        t = re.sub(r"\s+", " ", t).strip()
        if t and not t.startswith(_AI_FALLBACK_MARK):
            parts.append(t)
    return " ".join(parts)


def _digest_schema_json(date: str, desc: str, url: str) -> str:
    published = f"{date}T07:00:00+08:00"
    article = {
        "@type": "Article",
        "headline": f"財經日報 {date}",
        "description": desc,
        "image": [OG_IMAGE],
        "datePublished": published,
        "dateModified": published,
        "author": {"@type": "Organization", "name": "MarketDaily"},
        "publisher": PUBLISHER,
        "mainEntityOfPage": {"@type": "WebPage", "@id": url},
    }
    schema = {"@context": "https://schema.org", "@graph": [article]}
    return json.dumps(schema, ensure_ascii=False).replace("</", "<\\/")


def inject_archive_page(fpath: Path, date: str, dry: bool) -> bool:
    original = fpath.read_text(encoding="utf-8")
    html = _strip_existing_block(original)
    if not DIGEST_TITLE_RE.search(html):
        raise ValueError(f"{fpath.name}: 找不到 <title> 標籤,無法插入結構化資料區塊,需人工檢查頁面結構")
    url = f"{BASE}/output/digest_{date}"
    fallback = f"MarketDaily {date} AI 財經日報:美股與台股當日重點整理,個股分析全免費開放。"
    cand = _extract_tldr_text(html)
    # danger_chars 留預設(空集合):真實市場文字常見 "S&P 500" 這類字元,不整篇回退——
    # HTML 屬性槽用 html.escape() 個別轉義(desc_a),JSON-LD 槽用 json.dumps 處理的原始 desc。
    desc = _truncate_to_desc(cand, fallback, title=f"財經日報 {date}")
    desc_a = _esc(desc, quote=True)

    block_lines = [
        f'<meta name="description" content="{desc_a}">',
        f'<link rel="canonical" href="{url}">',
        '<meta property="og:type" content="article">',
        '<meta property="og:site_name" content="MarketDaily">',
        f'<meta property="og:title" content="財經日報 {date}">',
        f'<meta property="og:description" content="{desc_a}">',
        f'<meta property="og:url" content="{url}">',
        f'<meta property="og:image" content="{OG_IMAGE}">',
        '<meta name="twitter:card" content="summary_large_image">',
        f'<meta name="twitter:title" content="財經日報 {date}">',
        f'<meta name="twitter:description" content="{desc_a}">',
        f'<meta name="twitter:image" content="{OG_IMAGE}">',
    ]
    schema_json = _digest_schema_json(date, desc, url)
    block_lines.append(f'<script type="application/ld+json">{schema_json}</script>')

    new_html = DIGEST_TITLE_RE.sub(lambda m: m.group(0) + "\n" + _wrap_block(block_lines), html, count=1)

    if new_html == original:
        return False
    if dry:
        print(f"  [dry] {fpath.name}: would update (w{sum(2 if ord(c) > 0x2E7F else 1 for c in desc)})")
    else:
        fpath.write_text(new_html, encoding="utf-8")
        print(f"  [applied] {fpath.name}")
    return True


def backfill_archive(dry: bool) -> list:
    changed = []
    for p in sorted((DOCS / "output").glob("digest_*.html")):
        if "_personal_" in p.name or "_us" in p.name:
            continue  # 未進 sitemap(gen_sitemap.DATE_RE 排除),不加 SEO 標記
        m = DATE_RE.search(p.name)
        if not m:
            continue
        if inject_archive_page(p, m.group(1), dry):
            changed.append(p.name)
    return changed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--core", action="store_true")
    ap.add_argument("--archive", action="store_true")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()
    if not (args.core or args.archive or args.all):
        ap.error("需指定 --core / --archive / --all 至少一項")

    total = 0
    if args.core or args.all:
        print("== core pages ==")
        total += len(backfill_core(args.dry))
    if args.archive or args.all:
        print("== digest archive ==")
        total += len(backfill_archive(args.dry))
    print(f"{'[dry] ' if args.dry else ''}共 {total} 篇有改動")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
