"""MarketDaily 全站健康掃描 — 抓「用戶可見的錯誤」,供 site-doctor skill 第一步執行。

每個 check 都對應一次真實出包(出處寫在 check 旁),寧可 false positive 不可漏。
用法:python3 scan.py [--json]
exit 0 = 全過;exit 1 = 有 fail(stdout 列出每條)。
"""
import json
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

BASE = "https://marketdaily.ai"
WORKER = "https://marketdaily-webhook.delvin-12345678.workers.dev"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"

RESULTS = []


def check(name, ok, msg, severity="high"):
    RESULTS.append({"check": name, "ok": bool(ok), "severity": severity, "msg": msg})


def curl_json(url, timeout=30):
    try:
        out = subprocess.run(["curl", "-s", "-A", UA, "--max-time", str(timeout), url],
                             capture_output=True, text=True, timeout=timeout + 5)
        return json.loads(out.stdout)
    except Exception:
        return None


def curl_head(url, timeout=20):
    try:
        out = subprocess.run(["curl", "-s", "-A", UA, "-o", "/dev/null", "--max-time", str(timeout),
                              "-w", "%{http_code} %{size_download}", "-L", url],
                             capture_output=True, text=True, timeout=timeout + 5)
        code, size = out.stdout.split()
        return int(code), int(size)
    except Exception:
        return 0, 0


# ── 1. /stock-quotes 上限砍尾 + null 探針 ──────────────────────────────
# 出處 2026-06-10:slice(0,50) 把 56 支的最後 6 支(緯穎/威剛/十銓/雙鴻/金寶)靜默砍掉
# → 那幾檔永遠「···」;另 Yahoo 持續限流窗口會整批 null(6/8、6/10 兩次)。
def probe_quotes():
    us = ("AAPL,NVDA,MSFT,TSLA,AMD,GOOGL,AMZN,META,TSM,AVGO,MU,INTC,QCOM,NFLX,CRM,ORCL,"
          "ADBE,PLTR,SMCI,ARM,COIN,MSTR,UBER,ABNB,SNOW,PANW,CRWD,ANET,DELL,WDC,STX,LRCX,AMAT,KLAC")
    tw = "3661,1301,3443,2603,2330,2454,2317,2382,2308,3008,2412,2882,3034,3231,2356,6505,6669,3260,4967,3324,2312,2376"
    basket = (us + "," + tw).split(",")
    d = curl_json(f"{WORKER}/stock-quotes?tickers={','.join(basket)}")
    if not d or "quotes" not in d:
        check("quotes_api", False, "/stock-quotes 無回應或格式錯")
        return
    qs = d["quotes"]
    returned = {q["symbol"] for q in qs}
    dropped = [t for t in basket if t not in returned]
    check("quotes_cap_drop", not dropped,
          f"送 {len(basket)} 支回 {len(qs)} 筆" + (f",被砍掉:{dropped}" if dropped else " 全數回傳"))
    nulls = [q["symbol"] for q in qs if q.get("price") is None]
    if nulls:
        time.sleep(3)  # 偶發限流給一次機會
        d2 = curl_json(f"{WORKER}/stock-quotes?tickers={','.join(nulls)}")
        nulls = [q["symbol"] for q in (d2 or {}).get("quotes", []) if q.get("price") is None]
    check("quotes_nulls", len(nulls) == 0,
          f"重試後仍無報價(前台會卡「···」):{nulls}" if nulls else "全部有報價",
          severity="high" if len(nulls) > 2 else "med")


# ── 2. 戰績資料新鮮度 ───────────────────────────────────────────────
# 出處 2026-06-03:價格快取凍結 → 舊建議永遠待結;2026-05-28:抓失敗回 0 筆蓋掉好資料。
def probe_track_record():
    d = curl_json(f"{BASE}/data/track-record.json?cb={int(time.time())}")
    st = (d or {}).get("stats") or {}
    if not st:
        check("track_record_json", False, "track-record.json 抓不到或無 stats")
        return
    try:
        age_h = (datetime.now() - datetime.fromisoformat(st["generated_at"])).total_seconds() / 3600
    except Exception:
        age_h = 9e9
    check("track_record_fresh", age_h < 60, f"generated_at {st.get('generated_at')}({age_h:.0f}h 前)", severity="med")
    check("track_record_nonzero", st.get("total_records", 0) > 0, f"total_records={st.get('total_records')}")
    check("track_record_horizon", st.get("horizon") == "5d", f"horizon={st.get('horizon')}(應為 5d)", severity="med")


# ── 3. 日報 archive 新鮮度 ──────────────────────────────────────────
# 出處:公版日報曾停更 5/22-5/30(產完即失);manifest 漂移。
def probe_digest_archive():
    d = curl_json(f"{BASE}/output/manifest.json?cb={int(time.time())}")
    dates = (d or {}).get("dates") or []
    if not dates:
        check("digest_manifest", False, "manifest.json 抓不到或空")
        return
    latest = max(dates)
    age_d = (datetime.now() - datetime.fromisoformat(latest)).days
    check("digest_archive_fresh", age_d <= 4, f"最新公版日報 {latest}({age_d} 天前)", severity="med")


# ── 4. 資產健康 ────────────────────────────────────────────────────
# 出處 2026-06-10:og 全缺(分享無預覽)、hero 9MB(手機載不動)。
def probe_assets():
    code, size = curl_head(f"{BASE}/assets/og.png")
    check("og_image", code == 200 and size > 50_000, f"og.png http={code} size={size}")
    code, size = curl_head(f"{BASE}/hero-bg.mp4")
    check("hero_video", code == 200 and 0 < size < 2_500_000,
          f"hero-bg.mp4 http={code} size={size}(>2.5MB=壓縮回歸,404=遺失)")
    d = subprocess.run(["curl", "-s", "-A", UA, f"{BASE}/sitemap.xml"], capture_output=True, text=True).stdout
    locs = d.count("<loc>")
    check("sitemap", locs >= 30, f"sitemap {locs} URLs(<30=生成器壞掉)", severity="med")


# ── 5. 主要頁面渲染掃描(console error + 用戶可見錯誤符號)─────────────
# 出處:undefined/NaN/[object Object] 出現在卡片上、「···」卡死、JS 掛掉整區空白。
def probe_pages():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        check("pages_scan", False, "playwright 未安裝,跳過頁面掃描", severity="med")
        return
    pages = ["/", "/pricing", "/track-record", "/guide", "/blog/"]
    with sync_playwright() as p:
        try:
            b = p.chromium.launch(channel="chrome")
        except Exception:
            b = p.chromium.launch()
        for path in pages:
            pg = b.new_page(viewport={"width": 1280, "height": 900})
            errs, bad_resp = [], []
            pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.on("response", lambda r: bad_resp.append(f"{r.status} {r.url[:80]}")
                  if r.status >= 400 and "favicon" not in r.url else None)
            try:
                pg.goto(BASE + path, wait_until="networkidle", timeout=45000)
                pg.wait_for_timeout(2500)
                body = pg.inner_text("body")
                symptoms = []
                for pat, label in [("undefined", "undefined"), ("[object Object]", "[object Object]"),
                                   ("NaN%", "NaN%"), ("null%", "null%")]:
                    if pat in body:
                        symptoms.append(label)
                stuck = body.count("···")
                if stuck:
                    symptoms.append(f"「···」×{stuck}")
                check(f"page{path}", not (errs or symptoms),
                      f"console errors:{errs[:2]} 可見錯誤符號:{symptoms}" if (errs or symptoms) else "OK")
                if bad_resp:
                    check(f"page{path}_requests", False, f"失敗請求:{bad_resp[:3]}", severity="med")
            except Exception as e:
                check(f"page{path}", False, f"載入失敗:{str(e)[:80]}")
            pg.close()
        b.close()


# ── 6. 已知捏造內容不可復活 ──────────────────────────────────────────
# 出處 2026-07-03:testimonials.html/index.html 藏了 2026-05-23 launch 占位假見證
# (Jason L./Claire W./Alex K./林大哥/張先生/Michael C.)超過一個月沒人發現,見
# memory project_fake_testimonials_removed.md。防同款地雷用不同文案復活。
FABRICATED_MARKERS = ["Jason L.", "Claire W.", "Alex K.", "Michael C.",
                       "省了快 6 萬", "省 NT$6 萬", "退掉兩個月費"]


def probe_fabricated_content():
    for path in ["/", "/testimonials"]:
        html = subprocess.run(["curl", "-s", "-L", "-A", UA, f"{BASE}{path}"],
                              capture_output=True, text=True).stdout
        hits = [m for m in FABRICATED_MARKERS if m in html]
        check(f"no_fake_testimonials{path}", not hits,
              f"發現已知捏造見證關鍵字復活:{hits}" if hits else "OK")


# ── 7. Blog SEO 文章內容衛生 ──────────────────────────────────────────
# 出處 2026-07-04:seo_articles.py 生成文章時 LLM 偶爾把輸出包在 ```html...```
# 圍欄裡沒被 strip,直接洩漏進渲染頁面(使用者看得到字面 ```);同一批文章裡
# 另兩篇(2412/2882)寫死了跟真實股價差 4-7 倍的絕對數字(股價/EPS/配息金額),
# 已下架,見 memory project_blog_seo_fabricated_numbers.md。此檢查防圍欄外洩復發
# (絕對數字捏造無法機械檢測,靠 seo_articles.py 的 prompt 硬規則防範)。
def probe_blog_hygiene():
    blog_dir = Path(__file__).resolve().parents[1] / "docs" / "blog"
    files = [f for f in blog_dir.glob("*.html") if f.name != "index.html"]
    leaked = [f.name for f in files if "```" in f.read_text(encoding="utf-8")]
    check("blog_no_fence_leak", not leaked,
          f"文章殘留 markdown 圍欄未清:{leaked}" if leaked else f"{len(files)} 篇皆乾淨")


# ── 8. Blog 文章 JSON-LD structured data ──────────────────────────────
# 出處 2026-07-05:35 篇文章上線至今 0 篇有 schema.org Article markup,
# 搜尋引擎 rich snippet/知識圖譜零命中,是純技術債(非內容問題)。補上後
# 此檢查防未來新文章類型漏接 schema(seo_articles.py::write_article 統一注入)。
def probe_blog_schema():
    blog_dir = Path(__file__).resolve().parents[1] / "docs" / "blog"
    files = [f for f in blog_dir.glob("*.html") if f.name != "index.html"]
    missing, invalid = [], []
    required = ["@context", "@type", "headline", "datePublished", "dateModified"]
    for f in files:
        html = f.read_text(encoding="utf-8")
        m = re.search(r'<script type="application/ld\+json">(.+?)</script>', html, re.DOTALL)
        if not m:
            missing.append(f.name)
            continue
        try:
            obj = json.loads(m.group(1))
            if any(k not in obj for k in required):
                invalid.append(f.name)
        except Exception:
            invalid.append(f.name)
    ok = not missing and not invalid
    msg = f"{len(files)} 篇皆有效" if ok else f"缺 schema:{missing};壞 schema:{invalid}"
    check("blog_schema_present", ok, msg)


def main():
    probe_quotes()
    probe_track_record()
    probe_digest_archive()
    probe_assets()
    probe_pages()
    probe_fabricated_content()
    probe_blog_hygiene()
    probe_blog_schema()
    fails = [r for r in RESULTS if not r["ok"]]
    if "--json" in sys.argv:
        print(json.dumps(RESULTS, ensure_ascii=False, indent=1))
    else:
        for r in RESULTS:
            mark = "✅" if r["ok"] else ("🔴" if r["severity"] == "high" else "🟡")
            print(f"{mark} [{r['check']}] {r['msg']}")
        print(f"\n{'✅ 全部通過' if not fails else f'🚨 {len(fails)} 條 fail'}({len(RESULTS)} checks)")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
