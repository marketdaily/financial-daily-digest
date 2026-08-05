#!/usr/bin/env python3
"""代理瀏覽器 —— Claude 專屬、持續登入的 WSL Chromium。

為什麼存在(2026-08-05 Delvin 親令):
    「我不想要每一次我要用這個的時候都那麼麻煩,這也是我們最終自動化的其中一環。」
    以前每次需要「以 Delvin 的身分」操作某個後台(Meta 開發者後台、GSC、各平台後台),
    都要他本人去點。改成:**我自己有一個瀏覽器**,一次把登入狀態種進去就長期有效。

為什麼跑在 WSL 而不是遠端操控他的 Windows Chrome:
    ① 新版 Chrome 的 --remote-debugging-port 只綁 127.0.0.1(忽略 --remote-debugging-address),
       WSL 打不到,要開 relay 又可能跳 Windows 防火牆對話框 = 搶前景,違反鐵則。
    ② 他的 Chrome 在用的時候 profile 被鎖,cookie 檔複製不出來。
    ③ 跑在 WSL = 完全不干擾他,而且 WSL 與 Windows 共用同一個對外 IP,
       平台看到的來源 IP 與他平常一樣,不會被當成異地登入。

隱私邊界:種 cookie 一律**指定網域**,不整罐搬。見 seed_from_windows_chrome.sh。

用法:
    python3 agent_browser.py check                      看各站登入狀態
    python3 agent_browser.py import <cdp_cookies.json> facebook.com instagram.com
    python3 agent_browser.py shot <url> [out.png]       背景截圖(驗證用)
"""
import json
import sys
from pathlib import Path

PROFILE = Path.home() / ".claude-browser" / "profile"
STATE = Path.home() / ".claude-browser" / "sites.json"

# 每站一條「我登入了沒」的判準。用**帳號態才會出現的 cookie**,不是看頁面長相 ——
# 未登入的 facebook.com 也會回 200,拿 HTTP 狀態當判準等於永遠說「好的」。
SITES = {
    "facebook":  {"domains": ["facebook.com"],  "cookie": "c_user"},
    "instagram": {"domains": ["instagram.com"], "cookie": "sessionid"},
    "threads":   {"domains": ["threads.net", "threads.com"], "cookie": "sessionid"},
}


def context(headless=True):
    from playwright.sync_api import sync_playwright
    PROFILE.mkdir(parents=True, exist_ok=True)
    pw = sync_playwright().start()
    # channel="chrome" = 用 WSL 裝的系統 Chrome,不吃 playwright 自帶 chromium
    # (自帶那份版本與 playwright python 版本對不上,會叫人跑 playwright install)。
    # 用真 Chrome 也比較不會被平台的無頭偵測咬。
    ctx = pw.chromium.launch_persistent_context(
        str(PROFILE), channel="chrome",
        headless=headless, locale="zh-TW", timezone_id="Asia/Taipei",
        viewport={"width": 1440, "height": 900},
        user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"),
        args=["--disable-blink-features=AutomationControlled"])
    return pw, ctx


def _norm(c):
    """CDP cookie → Playwright cookie。sameSite 缺值必須補,Playwright 會擋掉非法值。"""
    ss = c.get("sameSite")
    return {
        "name": c["name"], "value": c["value"], "domain": c["domain"],
        "path": c.get("path", "/"),
        "expires": float(c.get("expires", -1)) if c.get("expires", -1) != -1 else -1,
        "httpOnly": bool(c.get("httpOnly")), "secure": bool(c.get("secure")),
        "sameSite": ss if ss in ("Strict", "Lax", "None") else "Lax",
    }


def cmd_import(path, domains):
    raw = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    cookies = raw.get("result", {}).get("cookies", raw if isinstance(raw, list) else [])
    keep = [c for c in cookies
            if any(c["domain"].lstrip(".").endswith(d) for d in domains)]
    if not keep:
        sys.exit(f"❌ 這份 cookie 裡沒有 {domains} 的任何一筆")
    pw, ctx = context()
    try:
        ctx.add_cookies([_norm(c) for c in keep])
        by = {}
        for c in keep:
            by[c["domain"].lstrip(".")] = by.get(c["domain"].lstrip("."), 0) + 1
        print(f"✅ 匯入 {len(keep)} 筆(只限 {', '.join(domains)}):")
        for d, n in sorted(by.items(), key=lambda x: -x[1]):
            print(f"     {d:28s} {n}")
    finally:
        ctx.close(); pw.stop()
    cmd_check()


def cmd_check():
    pw, ctx = context()
    try:
        have = {(c["domain"].lstrip("."), c["name"]) for c in ctx.cookies()}
        out = {}
        for site, cfg in SITES.items():
            ok = any((d, cfg["cookie"]) in have or
                     any(dom.endswith(d) and nm == cfg["cookie"] for dom, nm in have)
                     for d in cfg["domains"])
            out[site] = ok
            print(f"  {site:12s} {'✅ 已登入' if ok else '⛔ 未登入'}  (判準 cookie: {cfg['cookie']})")
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    finally:
        ctx.close(); pw.stop()


def cmd_shot(url, out="/tmp/agent_browser.png"):
    pw, ctx = context()
    try:
        pg = ctx.pages[0] if ctx.pages else ctx.new_page()
        pg.goto(url, wait_until="domcontentloaded", timeout=60000)
        pg.wait_for_timeout(3500)
        pg.screenshot(path=out)
        print(f"url={pg.url}\ntitle={pg.title()!r}\nshot={out}")
        print("---- body 前 800 字 ----")
        print(pg.inner_text("body")[:800])
    finally:
        ctx.close(); pw.stop()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    cmd = sys.argv[1]
    if cmd == "check":
        cmd_check()
    elif cmd == "import":
        cmd_import(sys.argv[2], sys.argv[3:] or ["facebook.com"])
    elif cmd == "shot":
        cmd_shot(sys.argv[2], *(sys.argv[3:4] or []))
    else:
        sys.exit(__doc__)
