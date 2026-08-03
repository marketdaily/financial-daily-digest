#!/usr/bin/env python3
"""scripts/archive_cta.py 自測(離線,零網路,<5s,exit 0=健康)。

涵蓋:冪等/重跑更新、錨點缺失 fail-loud、personal 檔排除、UTM 正確性、
文案合規(不得把個股分析與付費掛鉤/不得出現捏造數字)、以及**下游解析器迴歸**
(build_track_record.parse_digest_html / tldr_extract 的 indicator+sector 解析
在注入前後輸出必須逐位元相同)。
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

import archive_cta as A  # noqa: E402

FAILED = []


def check(cond, msg):
    if cond:
        print(f"  ok  {msg}")
    else:
        print(f"  FAIL {msg}")
        FAILED.append(msg)


PAGE = """<html><head><title>t</title></head><body>
<div class="wrapper">
  <div class="header"><h1>日報</h1></div>
  <div class="indicator-item">
    <div class="indicator-label">加權指數</div>
    <div class="indicator-value up">23,456</div>
    <div class="indicator-sub">+1.2%</div>
  </div>
  <div class="sector-item"><span class="sector-name">半導體</span><span class="sector-move up">+2.1%</span></div>
  <div class="signal-card">
    <div class="signal-ticker">TSM</div>
  </div>
  <div class="footer">disclaimer</div>
</div>
</body></html>
"""


def t_basic():
    print("[1] 注入基本行為")
    out, reason = A.inject(PAGE, "2026-08-03", False)
    check(reason is None, "有錨點的頁面注入成功")
    check(out.count(A.MARKER_START) == 2 and out.count(A.MARKER_END) == 2, "頂/底兩個區塊都注入")
    i_top = out.find(A.MARKER_START)
    i_header = out.find('<div class="header">')
    i_footer = out.find('<div class="footer">')
    i_bottom = out.rfind(A.MARKER_START)
    check(i_top < i_header, "頂部橫幅在 header 之前")
    check(i_header < i_bottom < i_footer, "底部 CTA 在 header 之後、footer 之前")
    check("免費訂閱明天的日報" in out, "主 CTA 文案在")
    # 原內容一字未動(把注入區塊剝掉要能還原成原文)
    check(A.strip_existing_block(out) == PAGE, "剝掉注入區塊可逐位元還原原文")


def t_idempotent():
    print("[2] 冪等 / 重跑更新")
    once, _ = A.inject(PAGE, "2026-08-03", False)
    twice, _ = A.inject(once, "2026-08-03", False)
    check(once == twice, "對已注入頁面重跑輸出不變(冪等)")
    # 文案變更後重跑必須更新,而不是被舊 marker 永久凍結
    stale = once.replace("免費訂閱明天的日報 →", "舊版文案")
    refreshed, _ = A.inject(stale, "2026-08-03", False)
    check("舊版文案" not in refreshed and "免費訂閱明天的日報" in refreshed,
          "舊版注入內容會被重算取代(不是有 marker 就跳過)")
    check(A.strip_existing_block(refreshed) == PAGE, "重算後原文仍完整")


def t_anchor_missing():
    print("[3] 錨點缺失 fail-loud")
    out, reason = A.inject("<html><body><div class=\"header\">x</div></body></html>", "2026-08-03", False)
    check(out is None and reason == "no_footer_anchor", "缺 footer 錨點 → 不寫檔並回報原因")
    out, reason = A.inject("<html><body><div class=\"footer\">x</div></body></html>", "2026-08-03", False)
    check(out is None and reason == "no_header_anchor", "缺 header 錨點 → 不寫檔並回報原因")
    out, reason = A.inject("<div class=\"footer\">f</div><div class=\"header\">h</div>", "2026-08-03", False)
    check(out is None and reason == "anchor_order", "錨點順序顛倒 → 拒絕注入")


def t_multi_header():
    print("[4] 內文嵌第二份 HTML 的舊檔(2 個 header)")
    page = PAGE.replace("<div class=\"signal-card\">",
                        "<div class=\"header\">內嵌週報標題</div>\n  <div class=\"signal-card\">")
    out, reason = A.inject(page, "2026-06-06", False)
    check(reason is None, "雙 header 檔仍可注入")
    i_top = out.find(A.MARKER_START)
    check(i_top < out.find('<div class="header">'), "橫幅插在第一個 header 之前(非內嵌那個)")
    check(out.count("這是 MarketDaily") == 1, "只注入一次橫幅")


def t_filename_and_utm():
    print("[5] 檔名解析與 UTM")
    check(A.parse_filename("digest_2026-08-03.html") == ("2026-08-03", False), "台股版檔名")
    check(A.parse_filename("digest_2026-08-03_us.html") == ("2026-08-03", True), "美股版檔名")
    check(A.parse_filename("digest_2026-08-03_personal_a.html") is None, "personal 檔不符命名 → 不處理")
    check(A.parse_filename("manifest.json") is None, "非 digest 檔不處理")
    url = A.cta_url("2026-08-03", False, "bottom")
    for frag in ("utm_source=digest_archive", "utm_medium=public_archive",
                 "utm_campaign=digest_2026-08-03", "utm_content=bottom", "#email-step"):
        check(frag in url, f"CTA 連結含 {frag}")
    us = A.cta_url("2026-08-03", True, "top")
    check("utm_campaign=digest_2026-08-03_us" in us and "utm_content=top" in us, "美股版 campaign/slot 正確")
    check(A.cta_url("2026-08-03", False, "top") != A.cta_url("2026-08-03", False, "bottom"),
          "頂/底 CTA 可分辨(utm_content)")


def t_edition_copy():
    print("[6] 版本別文案(不得對美股版說早上 7:00)")
    tw, _ = A.inject(PAGE, "2026-08-03", False)
    us, _ = A.inject(PAGE, "2026-08-03", True)
    check("每天早上 7:00" in tw and "台股日報" in tw, "台股版=早上 7:00")
    check("每天晚上 8:00" in us and "美股日報" in us, "美股版=晚上 8:00")
    check("每天早上 7:00" not in us, "美股版不得出現早上 7:00")
    check("台股版" in tw and "美股版" in us, "頂部橫幅標明版本")


def t_compliance():
    print("[7] 合規/誠實文案閘")
    out, _ = A.inject(PAGE, "2026-08-03", False)
    block = out[out.find(A.MARKER_START):]
    # 個股分析永不與付費掛鉤(COMPLIANCE_STRUCTURE.md);全面免費化後不得出現付費方案字眼
    for bad in ("Premium", "Pro 方案", "付費解鎖", "升級方案", "月費", "訂閱費", "NT$", "$9"):
        check(bad not in block, f"文案不含付費字眼「{bad}」")
    # 不得捏造社會證明數字(feedback_no_fake_numbers)
    nums = re.findall(r"\d[\d,]*\s*(?:位|人|名|萬)", block)
    check(not nums, f"文案不含訂閱人數類數字宣稱 {nums}")
    check("限時免費" in block and "早鳥" in block, "採用官方口徑(限時免費+早鳥)")
    check("不需信用卡" in block, "降風險微文案在")


def t_downstream_regression():
    print("[8] 下游解析器迴歸(真實存檔頁,注入前後輸出必須相同)")
    files = sorted((ROOT / "docs" / "output").glob("digest_*.html"))
    files = [f for f in files if "_personal_" not in f.name][-3:]
    if not files:
        check(False, "找不到真實存檔頁可測")
        return
    try:
        from build_track_record import parse_digest_html
        import importlib.util
        spec = importlib.util.spec_from_file_location("tldr_extract", ROOT / "marketing" / "tldr_extract.py")
        tldr = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tldr)
    except Exception as e:  # noqa: BLE001
        check(False, f"下游模組載入失敗:{e}")
        return
    for f in files:
        parsed = A.parse_filename(f.name)
        html = A.strip_existing_block(f.read_text(encoding="utf-8"))
        out, reason = A.inject(html, parsed[0], parsed[1])
        check(reason is None, f"{f.name} 可注入")
        if reason:
            continue
        check(parse_digest_html(parsed[0], html) == parse_digest_html(parsed[0], out),
              f"{f.name}: build_track_record 訊號卡解析不變")
        check(tldr.parse_indicators(html) == tldr.parse_indicators(out),
              f"{f.name}: tldr 指標解析不變")
        check(tldr.parse_sectors(html) == tldr.parse_sectors(out),
              f"{f.name}: tldr 類股解析不變")


def t_marker_corrupt():
    print("[10] marker 半毀 fail-loud(不得靜默安定在錯誤固定點)")
    once, _ = A.inject(PAGE, "2026-08-03", False)
    # 少一個 START:舊區塊比對不到 → 舊 CTA 降級成正文永久留著,同時又插一份新的
    orphan_start = once.replace(A.MARKER_START, "", 1)
    out, reason = A.inject(orphan_start, "2026-08-03", False)
    check(out is None and reason in ("marker_orphan", "marker_unpaired"),
          f"缺 START marker → 不寫檔並回報({reason})")
    # 少一個 END:非貪婪 regex 會從上方 START 一路吃到下方 END,刪掉整段正文
    orphan_end = once.replace(A.MARKER_END, "", 1)
    out, reason = A.inject(orphan_end, "2026-08-03", False)
    check(out is None and reason in ("marker_orphan", "marker_unpaired"),
          f"缺 END marker → 不寫檔並回報({reason})")
    # 成對但順序顛倒(END 在 START 前)
    swapped = PAGE.replace('<div class="header">',
                           f'{A.MARKER_END}\nx\n{A.MARKER_START}\n<div class="header">')
    out, reason = A.inject(swapped, "2026-08-03", False)
    check(out is None and reason == "marker_unpaired", "marker 順序顛倒 → 拒絕注入")
    # 健康頁面不得被誤判
    out, reason = A.inject(once, "2026-08-03", False)
    check(reason is None, "完整成對 marker 的頁面照常處理")


def t_io_error_isolation():
    print("[11] 單顆壞檔不得炸掉整批")
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        (d / "digest_2026-01-01.html").write_text(PAGE, encoding="utf-8")
        (d / "digest_2026-01-02.html").write_bytes(b"<html>\xff\xfe broken</html>")
        (d / "digest_2026-01-03.html").write_text(PAGE, encoding="utf-8")
        try:
            changed, skipped = A.run(dry=False, verbose=False, directory=d)
        except Exception as e:  # noqa: BLE001
            check(False, f"壞檔讓整批 traceback:{e.__class__.__name__}")
            return
        check(sorted(changed) == ["digest_2026-01-01.html", "digest_2026-01-03.html"],
              f"壞檔前後的好檔都處理完({changed})")
        check([n for n, r in skipped] == ["digest_2026-01-02.html"]
              and skipped[0][1].startswith("io_error:"),
              f"壞檔降級成單檔 skip({skipped})")
        check("免費訂閱明天的日報" in (d / "digest_2026-01-03.html").read_text(encoding="utf-8"),
              "排序在壞檔之後的檔案真的被寫入")


def t_atomic_write():
    print("[12] 寫檔原子性(行程中斷不得留下半截公開頁)")
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        target = Path(td) / "page.html"
        target.write_text("OLD-COMPLETE", encoding="utf-8")
        real_replace = A.os.replace

        def boom(*a, **k):
            raise RuntimeError("killed before rename")

        A.os.replace = boom
        try:
            A.atomic_write(target, "NEW-COMPLETE")
            raised = None
        except RuntimeError:
            raised = "RuntimeError"
        except OSError:
            raised = "OSError"
        finally:
            A.os.replace = real_replace
        # 目的地只由 rename 那一步碰到:rename 前掛掉 → 磁碟上仍是完整舊版,絕不是半截
        check(raised == "RuntimeError", f"rename 前中斷會傳播例外而非靜默直寫(got {raised})")
        check(target.read_text(encoding="utf-8") == "OLD-COMPLETE",
              "rename 前中斷:目的地仍是完整舊版")
        A.atomic_write(target, "NEW-COMPLETE")
        check(target.read_text(encoding="utf-8") == "NEW-COMPLETE", "正常路徑寫入成功")
        check(A.DOCS_OUTPUT not in A.TMP_DIR.parents and A.TMP_DIR != A.DOCS_OUTPUT,
              "tmp 檔不落在 docs/(殘留會被 wrangler 上傳並讓 docs-scoped cron 餓死)")


def t_no_personal_files():
    print("[9] personal 檔永不進處理清單")
    # 用臨時目錄種一顆真的 personal 檔來測——不能在 docs/output/ 種(那裡出現
    # *_personal_* 會觸發 cron_privacy_deploy_guard 擋死全站部署)。
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        for n in ("digest_2026-08-03.html", "digest_2026-08-03_us.html",
                  "digest_2026-08-03_personal_alice.html", "digest_2026-08-03_personal_bob_us.html",
                  "manifest.json", "digest_backup.html"):
            (d / n).write_text(PAGE, encoding="utf-8")
        names = [p.name for p in A.archive_files(d)]
        check(names == ["digest_2026-08-03.html", "digest_2026-08-03_us.html"],
              f"臨時目錄只挑出兩個公版檔(實得 {names})")
        changed, skipped = A.run(dry=True, verbose=False, directory=d)
        check(not any("_personal_" in c for c in changed), "run() 不會處理 personal 檔")
        check(len(changed) == 2 and not skipped, "run() 處理兩個公版檔且零跳過")
    real = [p.name for p in A.archive_files()]
    check(not any("_personal_" in n for n in real), "真實 docs/output 清單零 personal")
    check(all(n.startswith("digest_") and n.endswith(".html") for n in real), "清單只含 digest 存檔頁")


def main():
    for fn in (t_basic, t_idempotent, t_anchor_missing, t_multi_header, t_filename_and_utm,
               t_edition_copy, t_compliance, t_downstream_regression, t_marker_corrupt,
               t_io_error_isolation, t_atomic_write, t_no_personal_files):
        fn()
    print()
    if FAILED:
        print(f"archive_cta selftest: {len(FAILED)} FAILED")
        return 1
    print("archive_cta selftest: ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
