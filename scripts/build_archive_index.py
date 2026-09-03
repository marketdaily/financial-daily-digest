#!/usr/bin/env python3
"""
產生 docs/archive/index.html —— 公版日報存檔總索引(2026-09-03,總體檢 §2.2)。

131 篇 /output/digest_* 存檔頁原本是孤兒:站上沒有任何非 /output/ 頁面連過去、/output/ 本身
404,只靠 sitemap 被發現。本頁依月份列出全部存檔(台股日報/美股晚報各自標示),每筆用
archive_nav 算出的同一句主句(日期＋內文前三支個股)當連結文字,並帶各頁 meta description
當摘要。footer/blog/存檔頁尾都連到 /archive/,存檔頁群自此有站內入口。

殼沿用 docs/blog/index.html(深底、Inter、pill 篩選),資料全部從磁碟上的存檔頁讀——
零捏造、零手工維護。輸出決定性(排序固定),重跑內容不變就不寫檔(冪等)。
接在 ~/.marketdaily-fallback/digest_archive_seo_runner.sh 同一段流程,每日自動長。

用法:python scripts/build_archive_index.py [--dry]
"""
import argparse
import json
import re
import sys
from datetime import date as _date
from html import escape as _esc, unescape as _unesc
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(1, str(ROOT / "scripts"))
import archive_nav as N  # noqa: E402

DOCS = ROOT / "docs"
OUT = DOCS / "archive" / "index.html"
BASE = "https://marketdaily.ai"
OG_IMAGE = f"{BASE}/assets/og.png"
_DESC_RE = re.compile(r'<meta name="description" content="([^"]*)">')
_WEEKDAY = "一二三四五六日"


def collect() -> list:
    files = N.archive_files()
    items = []
    for p in files:
        d, is_us = N.parse_filename(p.name)
        html = p.read_text(encoding="utf-8", errors="ignore")
        names = N.extract_stock_names(html)
        m = _DESC_RE.search(html)
        desc = _unesc(m.group(1)) if m else ""
        items.append({
            "date": d, "is_us": is_us, "names": names,
            "title": N.headline(d, is_us, names),
            "url": f"/output/digest_{d}{'_us' if is_us else ''}",
            "desc": desc,
        })
    # 新→舊;同日台股(07:00)在美股(20:00)之前 → 倒序時美股先
    items.sort(key=lambda x: (x["date"], x["is_us"]), reverse=True)
    return items


def _month_label(ym: str) -> str:
    y, m = ym.split("-")
    return f"{y} 年 {int(m)} 月"


def _day_label(d: str) -> str:
    y, m, dd = (int(x) for x in d.split("-"))
    return f"{m:02d}/{dd:02d} 週{_WEEKDAY[_date(y, m, dd).weekday()]}"


def render(items: list) -> str:
    months = {}
    for it in items:
        months.setdefault(it["date"][:7], []).append(it)
    n_tw = sum(1 for i in items if not i["is_us"])
    n_us = len(items) - n_tw
    first, last = (items[-1]["date"], items[0]["date"]) if items else ("", "")

    sections = []
    for ym in sorted(months, reverse=True):
        cards = []
        for it in months[ym]:
            ed = "美股晚報" if it["is_us"] else "台股日報"
            color = "#fbbf24" if it["is_us"] else "#818cf8"
            stock = "、".join(it["names"]) if it["names"] else "當日市場重點"
            cards.append(
                f'<a class="card" data-f="{"us" if it["is_us"] else "tw"}" href="{it["url"]}">'
                f'<span class="tag" style="--tc:{color}">{ed}</span>'
                f'<div class="card-title">{_esc(_day_label(it["date"]))}｜{_esc(stock)}</div>'
                f'<div class="card-sum">{_esc(it["desc"])}</div>'
                f'<div class="card-meta"><span>{it["date"]}</span><span class="arrow">閱讀 →</span></div></a>'
            )
        sections.append(
            f'<section class="month" data-m="{ym}"><h2>{_month_label(ym)}'
            f'<span class="count">{len(months[ym])} 份</span></h2>'
            f'<div class="grid">{"".join(cards)}</div></section>'
        )

    desc = (f"MarketDaily 公版日報存檔:{first} 起每個交易日的台股日報(早上 7 點)與美股晚報"
            f"(晚上 8 點)全部公開,共 {len(items)} 份,依月份瀏覽。每份都有 TL;DR、個股進出場計畫與"
            f"財報行事曆,個股分析全免費。")
    schema = {
        "@context": "https://schema.org",
        "@graph": [{
            "@type": "CollectionPage",
            "name": "日報存檔 · MarketDaily",
            "description": desc,
            "url": f"{BASE}/archive/",
            "inLanguage": "zh-TW",
            "isPartOf": {"@id": f"{BASE}/#website"},
            "publisher": {"@type": "Organization", "name": "MarketDaily",
                          "logo": {"@type": "ImageObject", "url": f"{BASE}/logo-icon.svg"}},
            "hasPart": [{"@type": "Article", "headline": it["title"],
                         "url": BASE + it["url"], "datePublished": it["date"]}
                        for it in items[:30]],
        }, {
            "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "MarketDaily", "item": f"{BASE}/"},
                {"@type": "ListItem", "position": 2, "name": "日報存檔", "item": f"{BASE}/archive/"},
            ],
        }],
    }
    schema_json = json.dumps(schema, ensure_ascii=False).replace("</", "<\\/")
    title = "日報存檔 · 每日台股日報與美股晚報公開存檔 | MarketDaily"
    desc_a = _esc(desc, quote=True)

    return f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<link rel="icon" type="image/svg+xml" href="/logo-icon.svg">
<link rel="apple-touch-icon" href="/logo-icon.svg">
<title>{title}</title>
<meta name="description" content="{desc_a}">
<link rel="canonical" href="{BASE}/archive/">
<meta property="og:type" content="website">
<meta property="og:site_name" content="MarketDaily">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{desc_a}">
<meta property="og:url" content="{BASE}/archive/">
<meta property="og:image" content="{OG_IMAGE}">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{title}">
<meta name="twitter:description" content="{desc_a}">
<meta name="twitter:image" content="{OG_IMAGE}">
<script type="application/ld+json">{schema_json}</script>
<style>
:root{{ color-scheme:dark; --bg:#060611; --ink:#e8ebf5; --muted:#9aa3bd;
  --indigo:#818cf8; --indigo-l:#a5b4fc; --line:rgba(255,255,255,.08); --line-h:rgba(129,140,248,.42); }}
*{{ box-sizing:border-box; margin:0; padding:0; }}
body{{ background:radial-gradient(900px 500px at 82% -8%, rgba(99,102,241,.16), transparent 60%),
  radial-gradient(700px 460px at 8% 4%, rgba(56,189,248,.08), transparent 55%), var(--bg);
  color:var(--ink); font-family:'Inter','PingFang TC','Noto Sans TC',sans-serif; -webkit-font-smoothing:antialiased; min-height:100vh; }}
.topnav{{ display:flex; justify-content:space-between; align-items:center; gap:14px; padding:16px 24px;
  border-bottom:1px solid var(--line); max-width:1080px; margin:0 auto; }}
.topnav a{{ color:var(--indigo-l); text-decoration:none; font-weight:700; font-size:14px; }}
.topnav a:hover{{ color:#fff; }}
.topnav .r{{ display:flex; gap:18px; }}
.wrap{{ max-width:1080px; margin:0 auto; padding:52px 24px 96px; }}
.eyebrow{{ font-size:12px; font-weight:800; letter-spacing:.18em; text-transform:uppercase; color:var(--indigo-l); margin-bottom:14px; }}
h1{{ font-size:clamp(30px,5vw,44px); font-weight:900; color:#fff; letter-spacing:-.02em; line-height:1.12; }}
.sub{{ margin-top:14px; color:var(--muted); font-size:16px; line-height:1.6; max-width:60ch; }}
.filters{{ display:flex; flex-wrap:wrap; gap:10px; margin:34px 0 8px; }}
.pill{{ font:inherit; font-size:13.5px; font-weight:700; color:var(--muted); cursor:pointer;
  background:rgba(255,255,255,.04); border:1px solid var(--line); border-radius:999px; padding:8px 16px;
  transition:all .18s cubic-bezier(.22,1,.36,1); }}
.pill:hover{{ color:#fff; border-color:var(--line-h); }}
.pill.on{{ color:#0b0b16; background:linear-gradient(135deg,#a5b4fc,#818cf8); border-color:transparent; }}
.month{{ margin-top:34px; }}
.month h2{{ font-size:20px; font-weight:800; color:#fff; letter-spacing:-.01em; margin-bottom:14px;
  display:flex; align-items:baseline; gap:10px; }}
.month h2 .count{{ font-size:12.5px; font-weight:700; color:var(--muted); }}
.month.empty{{ display:none; }}
.grid{{ display:grid; grid-template-columns:repeat(auto-fill,minmax(320px,1fr)); gap:16px; }}
.card{{ position:relative; display:flex; flex-direction:column; padding:22px 22px 18px;
  background:rgba(255,255,255,.035); border:1px solid var(--line); border-radius:16px;
  text-decoration:none; color:inherit; overflow:hidden;
  transition:transform .2s cubic-bezier(.22,1,.36,1),border-color .2s,background .2s; }}
.card::before{{ content:""; position:absolute; inset:0 auto auto 0; width:100%; height:2px;
  background:linear-gradient(90deg,var(--tc,#818cf8),transparent); opacity:0; transition:opacity .2s; }}
.card:hover{{ transform:translateY(-3px); background:rgba(129,140,248,.08); border-color:var(--line-h); }}
.card:hover::before{{ opacity:.7; }}
.card.hide{{ display:none; }}
.tag{{ align-self:flex-start; font-size:11.5px; font-weight:800; letter-spacing:.02em; color:var(--tc);
  background:color-mix(in srgb,var(--tc) 14%,transparent); border:1px solid color-mix(in srgb,var(--tc) 32%,transparent);
  padding:3px 10px; border-radius:999px; margin-bottom:13px; }}
.card-title{{ font-size:16px; font-weight:750; color:#fff; line-height:1.45; letter-spacing:-.01em; }}
.card-sum{{ margin-top:9px; font-size:13.5px; line-height:1.6; color:var(--muted);
  display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; }}
.card-meta{{ margin-top:auto; padding-top:15px; display:flex; justify-content:space-between; align-items:center;
  font-size:12.5px; color:#6f7793; }}
.card-meta .arrow{{ color:var(--indigo-l); font-weight:700; opacity:0; transform:translateX(-4px); transition:all .2s; }}
.card:hover .arrow{{ opacity:1; transform:translateX(0); }}
.cta-top{{ display:flex; flex-wrap:wrap; gap:10px; align-items:center; justify-content:center;
  text-align:center; background:rgba(99,102,241,.10); border:1px solid rgba(99,102,241,.28);
  border-radius:12px; padding:12px 16px; margin:26px 0 0; font-size:14px; color:#c7d2fe; line-height:1.7; }}
.cta-top a{{ color:#fff; background:linear-gradient(135deg,#6366f1,#a855f7); font-weight:800;
  text-decoration:none; padding:8px 16px; border-radius:8px; white-space:nowrap; }}
footer{{ max-width:1080px; margin:0 auto; padding:28px 24px 48px; border-top:1px solid var(--line);
  display:flex; flex-wrap:wrap; gap:18px; font-size:13px; color:var(--muted); }}
footer a{{ color:var(--indigo-l); text-decoration:none; font-weight:600; }}
@media(max-width:520px){{ .grid{{ grid-template-columns:1fr; }} .topnav .r{{ gap:12px; }} }}
</style>
</head>
<body>
<div class="topnav"><a href="/">← MarketDaily</a><div class="r"><a href="/blog/">投資學堂</a><a href="/track-record">公開戰績</a><a href="/dashboard">我的後台</a></div></div>
<div class="wrap">
  <div class="eyebrow">Archive · 日報存檔</div>
  <h1>每一份日報,都公開留底</h1>
  <p class="sub">台股日報每天早上 7 點、美股晚報每天晚上 8 點寄出後,公版存檔就放在這裡——{first} 至 {last},共 {len(items)} 份(台股 {n_tw}・美股 {n_us})。判斷對錯全部可回頭查證,對照 <a href="/track-record" style="color:var(--indigo-l);text-decoration:none;font-weight:700;">公開戰績</a> 一起看。</p>
  <div class="cta-top">📬 不想每天來翻?留個 Email,同一份日報每天直接寄到你信箱——目前限時免費,現在訂閱未來恢復收費後仍永久免費。<a href="https://marketdaily.ai/?utm_source=archive_index&utm_medium=cta_top&utm_campaign=archive_index#email-step">免費訂閱 →</a></div>
  <div class="filters">
      <button class="pill on" data-f="all">全部 {len(items)}</button>
      <button class="pill" data-f="tw">🇹🇼 台股日報 {n_tw}</button>
      <button class="pill" data-f="us">🇺🇸 美股晚報 {n_us}</button>
  </div>
{"".join(sections)}
</div>
<footer>
  <a href="/">首頁</a><a href="/track-record">公開戰績</a><a href="/blog/">投資學堂</a><a href="/guide">新手教學</a><a href="/faq">常見問題</a><a href="/about">主編</a>
  <span style="margin-left:auto;">本頁內容為 AI 生成之一般性資訊整理,不構成投資建議。</span>
</footer>
<script>
(function(){{
  var pills=document.querySelectorAll('.pill');
  function apply(f){{
    pills.forEach(function(p){{ p.classList.toggle('on', p.dataset.f===f); }});
    document.querySelectorAll('.card').forEach(function(c){{ c.classList.toggle('hide', f!=='all' && c.dataset.f!==f); }});
    document.querySelectorAll('.month').forEach(function(m){{
      m.classList.toggle('empty', !m.querySelector('.card:not(.hide)'));
    }});
  }}
  pills.forEach(function(p){{ p.addEventListener('click', function(){{ apply(p.dataset.f); }}); }});
}})();
</script>
</body>
</html>
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()
    items = collect()
    if not items:
        print("build_archive_index: docs/output 找不到任何存檔頁,拒絕產空索引")
        return 1
    html = render(items)
    old = OUT.read_text(encoding="utf-8") if OUT.exists() else None
    if old == html:
        print(f"build_archive_index: unchanged ({len(items)} 份)")
        return 0
    if args.dry:
        print(f"build_archive_index: [dry] would write {OUT} ({len(items)} 份)")
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    print(f"build_archive_index: wrote {OUT} ({len(items)} 份)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
