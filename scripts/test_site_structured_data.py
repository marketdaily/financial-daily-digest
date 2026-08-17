#!/usr/bin/env python3
"""site_structured_data 的 archive 段自測(2026-08-18 建,open #236)。

為什麼要有:美股班存檔頁 `digest_YYYY-MM-DD_us.html` 被 `DATE_RE` 的 `$` 擋掉,
40/40 篇沒有 canonical/description/JSON-LD,而 gen_sitemap 用**同形狀的另一份** regex
⇒ 它們同時也不在 sitemap、站上沒有任何頁面連過去 = 對搜尋引擎完全不存在,
而且沒有任何自測在看這件事(08-11 只補了晚班窗口,腳本這邊照樣 skip)。

跑法:.venv/bin/python scripts/test_site_structured_data.py   (exit 0 = 健康)
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import gen_sitemap  # noqa: E402
import site_structured_data as ssd  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    print(f"  {'ok ' if cond else 'FAIL'}  {name}{'' if cond else ' — ' + detail}")
    if not cond:
        FAILS.append(name)


def main() -> int:
    # ① 兩支腳本各有一份 DATE_RE。它們必須認得同一組檔名——這正是這次的病灶
    #    (一邊放行、另一邊擋掉,結果是「有 SEO 標記但不在 sitemap」或反之)。
    names = ["digest_2026-08-17.html", "digest_2026-08-17_us.html",
             "digest_2026-08-17_personal_x.html", "tldr_2026-08-17.html"]
    a = {n: bool(ssd.DATE_RE.search(n)) for n in names}
    b = {n: bool(gen_sitemap.DATE_RE.search(n)) for n in names}
    check("兩支腳本的 DATE_RE 對同一組檔名判斷一致", a == b, f"{a} vs {b}")
    check("_us 會被收錄", a["digest_2026-08-17_us.html"])
    check("台股版會被收錄", a["digest_2026-08-17.html"])
    check("非 digest 檔不被誤收", not a["tldr_2026-08-17.html"])

    m = ssd.DATE_RE.search("digest_2026-08-17_us.html")
    check("market group 認得出美股版", bool(m) and m.group(2) == "_us",
          "整條 regex 不吃 _us" if not m else str(m.groups()))
    mt = ssd.DATE_RE.search("digest_2026-08-17.html")
    check("market group 對台股版是 None", bool(mt) and mt.group(2) is None,
          "regex 不吃台股版" if not mt else str(mt.groups()))

    # ② 兩版的 canonical 必須各自指向自己,否則等於把美股版判給台股版
    tw = ssd._digest_schema_json("2026-08-17", "d", f"{ssd.BASE}/output/digest_2026-08-17", "tw")
    us = ssd._digest_schema_json("2026-08-17", "d", f"{ssd.BASE}/output/digest_2026-08-17_us", "us")
    check("美股版 datePublished 用晚班時間", '"2026-08-17T20:00:00+08:00"' in us, us[:200])
    check("台股版 datePublished 用早班時間", '"2026-08-17T07:00:00+08:00"' in tw, tw[:200])
    check("兩版 headline 不同", ssd._digest_headline("2026-08-17", "tw")
          != ssd._digest_headline("2026-08-17", "us"))

    # ③ 真實樹:公開存檔頁一篇都不准少標記(逐日長出來的頁面群,最會復發的地方)
    pages = [p for p in (ssd.DOCS / "output").glob("digest_*.html") if "_personal_" not in p.name]
    check("真實樹上有存檔頁可驗", len(pages) >= 10, f"只有 {len(pages)} 篇")
    no_canon, no_ld, no_desc = [], [], []
    titles = {}
    for p in pages:
        t = p.read_text(encoding="utf-8", errors="ignore")
        if 'rel="canonical"' not in t:
            no_canon.append(p.name)
        if "application/ld+json" not in t:
            no_ld.append(p.name)
        if 'name="description"' not in t:
            no_desc.append(p.name)
        mt = re.search(r"<title>([^<]*)</title>", t)
        titles.setdefault(mt.group(1) if mt else "", []).append(p.name)
    check("每篇公開存檔頁都有 canonical", not no_canon, f"缺 {len(no_canon)}:{no_canon[:5]}")
    check("每篇都有 JSON-LD", not no_ld, f"缺 {len(no_ld)}:{no_ld[:5]}")
    check("每篇都有 meta description", not no_desc, f"缺 {len(no_desc)}:{no_desc[:5]}")
    dupes = {k: v for k, v in titles.items() if len(v) > 1}
    check("沒有兩篇共用同一個 <title>", not dupes, f"{list(dupes.items())[:3]}")

    # ④ canonical 必須指向自己(美股版指到台股版 = 自己把自己從索引移除)
    bad = []
    for p in pages:
        t = p.read_text(encoding="utf-8", errors="ignore")
        mc = re.search(r'<link rel="canonical" href="([^"]+)">', t)
        if mc and not mc.group(1).endswith("/" + p.name.replace(".html", "")):
            bad.append((p.name, mc.group(1)))
    check("canonical 指向自己", not bad, str(bad[:3]))

    # ⑤ sitemap 真的收了美股版(產生器改了但沒重跑 = 線上還是舊的)
    sm = (ssd.DOCS / "sitemap.xml").read_text(encoding="utf-8")
    us_pages = [p for p in pages if p.name.endswith("_us.html")]
    missing = [p.name for p in us_pages
               if f"/output/{p.name.replace('.html', '')}<" not in sm]
    check("sitemap 收錄全部美股版存檔頁", not missing, f"漏 {len(missing)}:{missing[:5]}")

    print(f"\nsite_structured_data selftest: {'ALL PASS' if not FAILS else str(len(FAILS)) + ' FAILED'}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
