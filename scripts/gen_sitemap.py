"""自動生成 docs/sitemap.xml。

核心頁面手列 + blog/*.html + docs/output/digest_*.html(公版日報 = 每日免費 SEO 內容)。
由 daily_digest workflow 在 persist archive 後執行,新日報自動進 sitemap。
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
BASE = "https://marketdaily.ai"

CORE = [
    ("/", "weekly", "1.0"),
    ("/pricing", "weekly", "0.9"),
    ("/track-record", "daily", "0.9"),
    ("/vs-chatgpt", "monthly", "0.8"),
    ("/vs", "monthly", "0.8"),
    ("/guide", "monthly", "0.7"),
    ("/about", "monthly", "0.5"),
    ("/contact", "monthly", "0.4"),
    ("/testimonials", "monthly", "0.5"),
    ("/blog/", "weekly", "0.7"),
]

DATE_RE = re.compile(r"digest_(\d{4}-\d{2}-\d{2})\.html$")


def main() -> int:
    urls = []
    for path, freq, pri in CORE:
        urls.append((BASE + path, freq, pri, None))

    for p in sorted((DOCS / "blog").glob("*.html")):
        if p.name == "index.html":
            continue
        urls.append((f"{BASE}/blog/{p.name.replace('.html', '')}", "monthly", "0.6", None))

    digests = []
    for p in (DOCS / "output").glob("digest_*.html"):
        if "_personal_" in p.name:
            continue
        m = DATE_RE.search(p.name)
        if m:
            digests.append((m.group(1), p.name))
    for d, name in sorted(digests, reverse=True):
        urls.append((f"{BASE}/output/{name.replace('.html', '')}", "never", "0.4", d))

    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for loc, freq, pri, lastmod in urls:
        lines.append("  <url>")
        lines.append(f"    <loc>{loc}</loc>")
        if lastmod:
            lines.append(f"    <lastmod>{lastmod}</lastmod>")
        lines.append(f"    <changefreq>{freq}</changefreq>")
        lines.append(f"    <priority>{pri}</priority>")
        lines.append("  </url>")
    lines.append("</urlset>")
    (DOCS / "sitemap.xml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[sitemap] {len(urls)} URLs written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
