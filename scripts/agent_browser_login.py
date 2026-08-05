#!/usr/bin/env python3
"""在代理瀏覽器裡開一個「有畫面」的視窗,讓 Delvin 登入一次 —— 之後永久有效。

為什麼是這條路(2026-08-05):
    Chrome 136+ 禁止在預設 profile 開遠端偵錯、cookie 又是 v20 App-Bound 綁原 profile,
    「從背景把他既有登入偷出來」被 Chrome 的防盜設計擋死(而且那方向本質是寫盜 cookie 工具)。
    Chrome 允許的做法就是:在這個瀏覽器裡**自己登入一次**,session 存進持久化 profile,
    往後所有背景操作都用它,不必再登入。FB session 動輒數月。

自動偵測:視窗開著,程式每 3 秒檢查登入判準 cookie(FB=c_user / IG=sessionid)有沒有出現。
    一出現就代表登入成功 → 自動存檔關閉,不必按任何鍵。等太久(預設 8 分鐘)才逾時。

⚠️ 這個視窗會出現在畫面上(WSLg)。依「絕不搶前景」鐵則,**只在 Delvin 主動要登入時跑**。

用法:
    python3 agent_browser_login.py                 FB(預設)
    python3 agent_browser_login.py instagram
    python3 agent_browser_login.py threads
"""
import sys
import time
from pathlib import Path

PROFILE = Path.home() / ".claude-browser" / "profile"
CFG = {
    "facebook":  ("https://www.facebook.com/login",            ["facebook.com"],  "c_user"),
    "instagram": ("https://www.instagram.com/accounts/login/", ["instagram.com"], "sessionid"),
    "threads":   ("https://www.threads.net/login",             ["threads.net", "threads.com"], "sessionid"),
    # Buyee 未登入時沒有可辨識的 session cookie(全是 GA/廣告追蹤),
    # 故改用「登入後才會出現的會員連結」當判準。第 4 元素 = CSS selector。
    "buyee":     ("https://buyee.jp/signup/login",             ["buyee.jp"],      None,
                  "a[href*='/mypage'], a[href*='logout'], a[href*='/signup/logout']"),
}
TIMEOUT_S = 480


def logged_in(ctx, domains, cookie):
    for c in ctx.cookies():
        dom = c["domain"].lstrip(".")
        if c["name"] == cookie and any(dom.endswith(d) for d in domains) and c.get("value"):
            return True
    return False


def logged_in_by_selector(pg, selector):
    """沒有可辨識 session cookie 的站(如 Buyee)改用登入後才出現的元素判準。"""
    try:
        return pg.query_selector(selector) is not None
    except Exception:
        return False


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "facebook"
    conf = CFG.get(which, CFG["facebook"])
    url, domains, cookie = conf[0], conf[1], conf[2]
    selector = conf[3] if len(conf) > 3 else None
    from playwright.sync_api import sync_playwright
    PROFILE.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(PROFILE), channel="chrome", headless=False,
            locale="zh-TW", timezone_id="Asia/Taipei",
            viewport={"width": 1280, "height": 860},
            args=["--disable-blink-features=AutomationControlled"])
        pg = ctx.pages[0] if ctx.pages else ctx.new_page()
        pg.goto(url, wait_until="domcontentloaded")
        print(f"[登入視窗已開] {which}: {url}")
        print("在視窗裡完成登入即可,不用按任何鍵 —— 我偵測到就會自動存檔關閉。")
        deadline = time.time() + TIMEOUT_S
        ok = False
        while time.time() < deadline:
            try:
                hit = (logged_in(ctx, domains, cookie) if cookie
                       else logged_in_by_selector(pg, selector))
                if hit:
                    ok = True
                    break
            except Exception:
                pass  # 導頁途中 context 短暫忙,略過這輪
            time.sleep(3)
        # 多等 2 秒讓所有 cookie 落定再關
        time.sleep(2)
        ctx.close()
    print("✅ 偵測到登入,已關閉存檔。" if ok else "⏱️ 逾時未偵測到登入(session 未變更)。")
    print("確認:python3 scripts/agent_browser.py check")


if __name__ == "__main__":
    main()
