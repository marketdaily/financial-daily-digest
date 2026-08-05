#!/usr/bin/env python3
"""在代理瀏覽器裡開一個「有畫面」的視窗,讓 Delvin 登入一次 —— 之後永久有效。

為什麼是這條路(2026-08-05):
    Chrome 136+ 禁止在預設 profile 開遠端偵錯、cookie 又是 v20 App-Bound 綁原 profile,
    「從背景把他既有登入偷出來」被 Chrome 的防盜設計擋死(而且那方向本質是寫盜 cookie 工具)。
    Chrome 允許的做法就是:在這個瀏覽器裡**自己登入一次**,session 存進持久化 profile,
    往後所有背景操作都用它,不必再登入。FB session 動輒數月。

⚠️ 這個視窗會出現在畫面上(WSLg)。依「絕不搶前景」鐵則,**只在 Delvin 主動要登入時跑**,
   不要在他忙別的事時自動彈出來。跑起來後他自己操作,登完關掉視窗即可。

用法:
    python3 agent_browser_login.py                 開登入視窗(預設先到 facebook)
    python3 agent_browser_login.py instagram       開 IG 登入
    python3 agent_browser_login.py threads
"""
import sys
from pathlib import Path

PROFILE = Path.home() / ".claude-browser" / "profile"
START = {
    "facebook":  "https://www.facebook.com/login",
    "instagram": "https://www.instagram.com/accounts/login/",
    "threads":   "https://www.threads.net/login",
}


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "facebook"
    url = START.get(which, START["facebook"])
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
        print(f"視窗已開:{url}")
        print("在視窗裡登入完成後,把這個終端機的 Enter 按下去(或直接關視窗)——session 會留在代理瀏覽器。")
        try:
            input()
        except (EOFError, KeyboardInterrupt):
            pass
        ctx.close()
    print("已關閉。用 `python3 scripts/agent_browser.py check` 確認登入狀態。")


if __name__ == "__main__":
    main()
