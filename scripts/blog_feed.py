#!/usr/bin/env python3
"""
Blog RSS 2.0 feed 生成器 — 掃 docs/blog/*.html 產 docs/feed.xml

為什麼要有 feed(reach 資產,不是裝飾):
  - Substack / Beehiiv 可用 feed URL 一鍵自動匯入全部 blog(growth 研究鎖定的管道)
  - RSS 讀者(Feedly 等)、內容聚合器可訂閱;RSS→自動社群同步(IFTTT/Make/Buffer)
  - 每篇新週更文章自動進 feed → 內容規模化外送,零人工

設計鐵則:
  - 純標準庫、無網路;冪等(同一批文章 → 位元相同的 feed,lastBuildDate=最新文章日而非 now())
  - item link 帶 utm_source=rss(beacon 尊重明寫的 utm → RSS 點擊歸因為 rss 非 blog)
  - guid=乾淨 canonical(isPermaLink=true,穩定不變,供匯入器當正典)
  - XML 全跳脫;產圖/日期解析任一失敗只跳過該篇並印 stderr,絕不靜默漏或整批崩

用法:
  python scripts/blog_feed.py            # 產 docs/feed.xml
  python scripts/blog_feed.py --dry      # 只 print 摘要不寫檔
"""
import argparse
import html
import re
import sys
from datetime import datetime, timezone, timedelta
from email.utils import format_datetime
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

ROOT = Path(__file__).resolve().parents[1]
BLOG_DIR = ROOT / "docs" / "blog"
FEED_PATH = ROOT / "docs" / "feed.xml"

SITE = "https://marketdaily.ai"
FEED_URL = f"{SITE}/feed.xml"
BLOG_URL = f"{SITE}/blog/"
CHANNEL_TITLE = "MarketDaily 個股分析"
CHANNEL_DESC = "MarketDaily 個股深度分析 — 美股、台股長尾主題,每週更新。"
CHANNEL_IMAGE = f"{SITE}/assets/og.png"
TW = timezone(timedelta(hours=8))
MAX_ITEMS = 200  # feed 大小上限;超過只留最新,並印出被裁掉幾篇(絕不靜默截斷)

_TITLE_RE = re.compile(r"<title>(.+?)\s*\|", re.DOTALL)
_DESC_RE = re.compile(r'<meta\s+name="description"\s+content="(.*?)"', re.DOTALL)
_OGIMG_RE = re.compile(r'<meta\s+property="og:image"\s+content="(.*?)"', re.DOTALL)
_CANON_RE = re.compile(r'<link\s+rel="canonical"\s+href="(.*?)"', re.DOTALL)
_DATE_RE = re.compile(r'"datePublished"\s*:\s*"([^"]+)"')


def _parse_pubdate(raw: str) -> datetime:
    """把 schema datePublished(可能是 'YYYY-MM-DD' 或帶時區的 ISO8601)轉成 aware datetime。
    純日期或無時區一律補台北時區,保證跨環境確定性。"""
    s = (raw or "").strip()
    dt = None
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        try:
            dt = datetime.strptime(s[:10], "%Y-%m-%d")
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TW)
    return dt


def _ticker_category(slug: str):
    """slug 首段當分類標籤(2330 / AAPL);非個股代號型(term/macro 等)就不標。"""
    head = slug.split("-", 1)[0]
    return head.upper() if re.fullmatch(r"[A-Za-z0-9]{2,6}", head) else None


def collect_items() -> list:
    """掃 blog 目錄,回傳排序好(新→舊)的 feed item 清單。壞檔跳過並印 stderr。"""
    items = []
    for f in sorted(BLOG_DIR.glob("*.html")):
        if f.stem == "index":
            continue
        try:
            txt = f.read_text(encoding="utf-8")
        except Exception as e:
            print(f"  [feed] skip {f.name}: read {type(e).__name__}", file=sys.stderr)
            continue
        dm = _DATE_RE.search(txt)
        pub = _parse_pubdate(dm.group(1)) if dm else None
        if pub is None:
            print(f"  [feed] skip {f.name}: no parseable datePublished", file=sys.stderr)
            continue
        tm = _TITLE_RE.search(txt)
        title = html.unescape(tm.group(1)).strip() if tm else f.stem
        dsm = _DESC_RE.search(txt)
        desc = html.unescape(dsm.group(1)).strip() if dsm else title
        cm = _CANON_RE.search(txt)
        canonical = cm.group(1).strip() if cm else f"{SITE}/blog/{f.stem}.html"
        om = _OGIMG_RE.search(txt)
        og_image = om.group(1).strip() if om else CHANNEL_IMAGE
        items.append({
            "slug": f.stem, "title": title, "desc": desc, "canonical": canonical,
            "og_image": og_image, "pub": pub, "category": _ticker_category(f.stem),
        })
    # 新→舊;同日以 slug 決定序,確保冪等
    items.sort(key=lambda it: (it["pub"], it["slug"]), reverse=True)
    if len(items) > MAX_ITEMS:
        print(f"  [feed] {len(items)} 篇超過上限 {MAX_ITEMS},只保留最新 {MAX_ITEMS}(裁掉 {len(items) - MAX_ITEMS} 篇)")
        items = items[:MAX_ITEMS]
    return items


def _attr(url: str) -> str:
    """URL 進 XML 屬性:跳脫 & < > " 。"""
    return xml_escape(url, {'"': "&quot;"})


def _item_xml(it: dict) -> str:
    sep = "&" if "?" in it["canonical"] else "?"  # canonical 若已帶 query 就用 & 續接,避免雙 ?
    link = f"{it['canonical']}{sep}utm_source=rss&utm_medium=feed&utm_content={it['slug']}"
    parts = [
        "  <item>",
        f"    <title>{xml_escape(it['title'])}</title>",
        f"    <link>{_attr(link)}</link>",
        f'    <guid isPermaLink="true">{_attr(it["canonical"])}</guid>',
        f"    <pubDate>{format_datetime(it['pub'])}</pubDate>",
        f"    <description>{xml_escape(it['desc'])}</description>",
    ]
    if it["category"]:
        parts.append(f"    <category>{xml_escape(it['category'])}</category>")
    parts.append(f'    <media:thumbnail url="{_attr(it["og_image"])}"/>')
    parts.append(f'    <media:content url="{_attr(it["og_image"])}" medium="image"/>')
    parts.append("  </item>")
    return "\n".join(parts)


def build_feed_xml(items: list) -> str:
    # lastBuildDate = 最新文章日(非 now())→ 冪等,無雜訊 diff
    last_build = items[0]["pub"] if items else datetime(2026, 1, 1, tzinfo=TW)
    head = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom" '
        'xmlns:media="http://search.yahoo.com/mrss/">',
        "<channel>",
        f"  <title>{xml_escape(CHANNEL_TITLE)}</title>",
        f"  <link>{_attr(BLOG_URL)}</link>",
        f'  <atom:link href="{_attr(FEED_URL)}" rel="self" type="application/rss+xml"/>',
        f"  <description>{xml_escape(CHANNEL_DESC)}</description>",
        "  <language>zh-tw</language>",
        f"  <lastBuildDate>{format_datetime(last_build)}</lastBuildDate>",
        "  <ttl>720</ttl>",
        "  <generator>MarketDaily blog_feed.py</generator>",
        "  <image>",
        f"    <url>{_attr(CHANNEL_IMAGE)}</url>",
        f"    <title>{xml_escape(CHANNEL_TITLE)}</title>",
        f"    <link>{_attr(BLOG_URL)}</link>",
        "  </image>",
    ]
    body = [_item_xml(it) for it in items]
    tail = ["</channel>", "</rss>", ""]
    return "\n".join(head + body + tail)


def build_feed(dry: bool = False) -> Path:
    items = collect_items()
    xml = build_feed_xml(items)
    if dry:
        print(f"  [dry] feed.xml — {len(items)} items(newest: {items[0]['title'] if items else '—'})")
        return FEED_PATH
    FEED_PATH.write_text(xml, encoding="utf-8")
    print(f"  ✓ feed.xml ({len(items)} items)")
    return FEED_PATH


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    build_feed(ap.parse_args().dry)
