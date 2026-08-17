#!/usr/bin/env python3
"""就地訂閱表單的**真瀏覽器**端到端驗證(headless,零真實網路,不製造訂閱者、不寄信)。

單元測試守的是「產生出來的字串長對」,這支守的是「瀏覽器真的跑得動」——JS 語法錯、
id 對不上、事件沒綁到、Promise 分支寫反,字串比對一個都抓不到。

**不打真的 API**:`page.route` 攔截 `**/subscribe-free-direct` 用假回應餵四種分支
(ok / resubscribe_pending / undeliverable_email / 網路失敗)。這也是死線要求 ——
自測絕不可以真的寄信或建立訂閱者。

用法:./.venv/bin/python scripts/test_inline_subscribe_e2e.py [--headed]
exit 0 = 全過
"""
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "docs" / "output" / "digest_2026-08-17.html"
BLOG = ROOT / "docs" / "blog" / "eng-llm-council-judge-en-202608.html"

FAILED = []


def check(name, cond, extra=""):
    if cond:
        print(f"  ok  {name}")
    else:
        FAILED.append(name)
        print(f"  FAIL {name}{(' — ' + extra) if extra else ''}")


def run_page(pw, path: Path, *, response=None, fail=False, query=""):
    """開一頁、攔截訂閱 API、填 email 送出,回傳 (訊息文字, 按鈕文字, 送出的 body, console 錯誤)。"""
    browser = pw.chromium.launch()
    page = browser.new_page()
    errors, sent = [], {}
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

    def handler(route, request):
        try:
            sent.update(json.loads(request.post_data or "{}"))
        except Exception:
            pass
        if fail:
            route.abort()
        else:
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(response or {"ok": True}))

    page.route("**/subscribe-free-direct", handler)
    page.goto(path.as_uri() + query)
    page.fill("#mdsub-email", "someone@example.com")
    page.click("#mdsub-btn")
    page.wait_for_timeout(400)
    msg = page.inner_text("#mdsub-msg")
    btn = page.inner_text("#mdsub-btn")
    disabled = page.get_attribute("#mdsub-email", "disabled") is not None
    browser.close()
    return msg, btn, sent, errors, disabled


def main():
    for f in (ARCHIVE, BLOG):
        if not f.exists():
            print(f"找不到待測頁面 {f} —— 先跑 archive_cta.py / backfill_bottom_form")
            return 2

    with sync_playwright() as pw:
        print("[1] 公版存檔頁:表單存在且送得出去(成功分支)")
        msg, btn, sent, errors, disabled = run_page(pw, ARCHIVE)
        check("零 JS 錯誤", not errors, str(errors[:2]))
        check("成功後顯示訂閱成功", "訂閱成功" in msg, msg)
        check("按鈕變成已訂閱", "已訂閱" in btn, btn)
        check("email 欄位鎖起來(防重複送)", disabled)
        check("送出的 email 正確", sent.get("email") == "someone@example.com", str(sent))
        check("歸因 utm_source=digest_archive", sent.get("utm_source") == "digest_archive", str(sent))
        check("歸因 utm_medium=public_archive", sent.get("utm_medium") == "public_archive")
        check("歸因 campaign 對得上該日日報",
              sent.get("utm_campaign") == "digest_2026-08-17", str(sent.get("utm_campaign")))
        check("歸因 utm_content 標出是就地表單", sent.get("utm_content") == "inline_form")

        print("[2] 網址帶真 utm 時,歸因用真的(不被頁面預設蓋掉)")
        _, _, sent2, _, _ = run_page(pw, ARCHIVE, query="?utm_source=threads&utm_medium=social")
        check("utm_source 用網址的", sent2.get("utm_source") == "threads", str(sent2))
        check("utm_medium 用網址的", sent2.get("utm_medium") == "social", str(sent2))

        print("[3] 退訂過的人:不可謊稱訂閱成功")
        msg3, btn3, _, _, _ = run_page(pw, ARCHIVE,
                                       response={"ok": True, "resubscribe_pending": True, "sent": True})
        check("講的是確認信而不是訂閱成功", "確認信" in msg3 and "訂閱成功" not in msg3, msg3)
        check("按鈕不說已訂閱", "已訂閱" not in btn3, btn3)

        print("[4] 收不到信 / 網路失敗:錯誤講得出來且可重試")
        msg4, btn4, _, _, dis4 = run_page(pw, ARCHIVE, response={"error": "undeliverable_email"})
        check("提示拼字問題", "拼字" in msg4, msg4)
        check("按鈕回到可再送的狀態", "免費訂閱" in btn4, btn4)
        check("email 欄位沒被鎖住", not dis4)
        msg5, btn5, _, _, _ = run_page(pw, ARCHIVE, fail=True)
        check("網路錯誤有話講", "網路錯誤" in msg5, msg5)
        check("網路錯誤後可重試", "免費訂閱" in btn5, btn5)

        print("[5] blog 頁(近 7 日流量第一的英文工程文)")
        msgb, btnb, sentb, errb, _ = run_page(pw, BLOG)
        check("零 JS 錯誤", not errb, str(errb[:2]))
        check("英文頁講英文", "You're in" in msgb, msgb)
        check("英文按鈕", "Subscribed" in btnb, btnb)
        check("歸因 utm_source=blog", sentb.get("utm_source") == "blog", str(sentb))
        check("沿用該頁原本的 eng_article 歸因(不改名既有帳)",
              sentb.get("utm_medium") == "eng_article"
              and sentb.get("utm_campaign") == "council_judge", str(sentb))

        print("[6] 無效 email 在前端就擋下來(不浪費一次 rate limit)")
        # 兩道防線分工:`type=email` 的原生驗證擋沒有 @ 的(瀏覽器自己跳提示泡泡,
        # submit 事件根本不會發生 ⇒ 這時 #mdsub-msg 是空的,那是正常的);
        # 原生驗證放行、我們的 regex 才擋得住的(如 a@b 少了網域點)由 JS 出訊息。
        for bad, expect_msg in (("not-an-email", False), ("a@b", True)):
            browser = pw.chromium.launch()
            page = browser.new_page()
            hits = []
            page.route("**/subscribe-free-direct", lambda r, q: (hits.append(1), r.abort()))
            page.goto(ARCHIVE.as_uri())
            page.fill("#mdsub-email", bad)
            page.click("#mdsub-btn")
            page.wait_for_timeout(300)
            m = page.inner_text("#mdsub-msg")
            valid = page.eval_on_selector("#mdsub-email", "el => el.checkValidity()")
            browser.close()
            check(f"『{bad}』沒有打出任何請求", not hits)
            if expect_msg:
                check(f"『{bad}』原生驗證放行,由 JS 提示無效", valid and "有效" in m, f"valid={valid} msg={m}")
            else:
                check(f"『{bad}』被瀏覽器原生驗證擋住", not valid, f"valid={valid}")

    if FAILED:
        print(f"\ninline_subscribe e2e: {len(FAILED)} FAILED — {FAILED}")
        return 1
    print("\ninline_subscribe e2e: ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
