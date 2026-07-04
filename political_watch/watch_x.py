"""政壇市場訊號 — X 掃描器(零 xAI 成本路線)。

用 Playwright + 用戶自己的 X 登入 session,每 15 分鐘掃追蹤名單的新貼文,
送 alert-worker /political-ingest:worker 端 Claude 判讀市場關聯與嚴重度
→ 走既有 LINE 推播管線(去重/門檻/操作立場)。

登入 session 用 Playwright storage_state(明文 JSON,可跨機/跨平台搬):
在有顯示器的機器(Mac)登入匯出一次,把 auth_state.json 搬到無頭機(winrig)即可。

用法:
  python3 watch_x.py --login   # 開視窗讓用戶手動登入 X 一次(session 存 auth_state.json)
  python3 watch_x.py           # 掃一輪+上送(systemd timer / launchd 每 15 分鐘跑這個)
  python3 watch_x.py --dry     # 掃+分析但不真推 LINE
"""
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
AUTH_STATE = Path(os.environ.get("POLITICAL_AUTH_STATE", HERE / "auth_state.json"))
STATE = HERE / "state.json"
LOG = HERE / "watch.log"
WORKER = "https://marketdaily-alert-worker.delvin-12345678.workers.dev"

# 與 alert-worker/src/political_source.js、grok_political.py 同名單,改要三邊同步
HANDLES = [
    "realDonaldTrump", "WhiteHouse", "POTUS", "USTreasury", "scottbessent",
    "CommerceGov", "USTradeRep", "federalreserve", "SECGov", "elonmusk",
]

MAX_AGE_MIN = 75  # 只送這麼新的貼文(cron 15 分鐘,留重疊餘裕;worker 端還有 48h 去重)

# scrape 後回報 session 是否仍有效(撞到 X 登入牆=失效),main 用來通知 admin 重登
STATUS = {"alive": True, "hit_login": False}


def log(msg):
    line = f"[{datetime.now().strftime('%m-%d %H:%M:%S')}] {msg}"
    print(line)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def load_state():
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {"seen": {}}


def save_state(st):
    # seen 只留 3 天,別讓檔案無限長
    cutoff = time.time() - 3 * 86400
    st["seen"] = {k: v for k, v in st["seen"].items() if v > cutoff}
    STATE.write_text(json.dumps(st))


def _launch(p, headless):
    # winrig(ubuntu26.04)playwright chromium 下載被擋 → 用系統 google-chrome(channel)
    # Mac 有 bundled chromium → fallback;兩邊同一份程式
    try:
        return p.chromium.launch(channel="chrome", headless=headless)
    except Exception:
        return p.chromium.launch(headless=headless)


def scrape(login_mode=False):
    from playwright.sync_api import sync_playwright
    posts = []
    with sync_playwright() as p:
        browser = _launch(p, headless=not login_mode)
        if login_mode:
            ctx = browser.new_context(viewport={"width": 1280, "height": 900})
            pg = ctx.new_page()
            pg.goto("https://x.com/login")
            print("\n>>> 請在開啟的視窗登入你的 X 帳號(含兩步驟驗證)。")
            print(">>> 登入完成、看到首頁時間軸後,直接關閉視窗即可。\n")
            try:
                pg.wait_for_event("close", timeout=600000)
            except Exception:
                pass
            try:
                ctx.storage_state(path=str(AUTH_STATE))
                log(f"登入 session 已存 {AUTH_STATE}")
            except Exception as e:
                log(f"存 session 失敗:{str(e)[:120]}")
            ctx.close()
            browser.close()
            return []
        if not AUTH_STATE.exists():
            log(f"缺 {AUTH_STATE},先跑 python3 watch_x.py --login 登入")
            browser.close()
            return []
        ctx = browser.new_context(
            storage_state=str(AUTH_STATE),
            viewport={"width": 1280, "height": 900},
        )
        pg = ctx.new_page()
        for h in HANDLES:
            try:
                pg.goto(f"https://x.com/{h}", wait_until="domcontentloaded", timeout=30000)
                pg.wait_for_timeout(3500)
                if "/login" in pg.url or "Log in" in pg.title():
                    log(f"@{h}: 未登入(session 失效)→ 跑 python3 watch_x.py --login 重登")
                    STATUS["alive"] = False
                    STATUS["hit_login"] = True
                    break
                items = pg.evaluate("""() => {
                    const out = [];
                    for (const a of document.querySelectorAll('article')) {
                        const t = a.querySelector('time');
                        const link = t ? t.closest('a') : null;
                        const txtEl = a.querySelector('[data-testid="tweetText"]');
                        if (!t || !link || !txtEl) continue;
                        // 置頂貼文可能是舊文,靠時間過濾;轉推跳過(socialContext 標記)
                        if (a.querySelector('[data-testid="socialContext"]')) continue;
                        out.push({ time: t.getAttribute('datetime'),
                                   url: 'https://x.com' + link.getAttribute('href'),
                                   text: txtEl.innerText });
                        if (out.length >= 6) break;
                    }
                    return out;
                }""")
                fresh = 0
                for it in items:
                    try:
                        ts = datetime.fromisoformat(it["time"].replace("Z", "+00:00"))
                    except Exception:
                        continue
                    age = (datetime.now(timezone.utc) - ts).total_seconds() / 60
                    if age > MAX_AGE_MIN:
                        continue
                    posts.append({"handle": h, "text": it["text"][:600],
                                  "url": it["url"], "posted_at": it["time"]})
                    fresh += 1
                log(f"@{h}: 頁面 {len(items)} 則,{MAX_AGE_MIN}min 內 {fresh} 則")
                pg.wait_for_timeout(800)
            except Exception as e:
                log(f"@{h}: 抓取失敗 {str(e)[:100]}")
        ctx.close()
        browser.close()
    return posts


def send(posts, dry=False):
    tok = ""
    for line in (HERE / ".env").read_text().splitlines():
        if line.startswith("POLITICAL_INGEST_TOKEN="):
            tok = line.split("=", 1)[1].strip()
    if not tok:
        log("缺 POLITICAL_INGEST_TOKEN,中止")
        return
    body = json.dumps({"posts": posts, "dry": dry}).encode()
    req = urllib.request.Request(
        f"{WORKER}/political-ingest", data=body, method="POST",
        headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json",
                 "User-Agent": "political-watch/1.0"},
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        out = json.loads(r.read().decode())
    rep = out.get("report") or {}
    log(f"上送 {len(posts)} 則 → 分析 {out.get('analyzed')} 則,訊號 {len(out.get('signals') or [])},"
        f"達標 {rep.get('qualified', 0)},推播 {rep.get('pushed', 0)}{'(dry)' if dry else ''}")
    if out.get("signals"):
        for s in out["signals"]:
            log(f"  · sev{s['severity']} [{s['kind']}] {s['name_zh']}:{s['headline_zh'][:50]}")


def _read_token():
    for line in (HERE / ".env").read_text().splitlines():
        if line.startswith("POLITICAL_INGEST_TOKEN="):
            return line.split("=", 1)[1].strip()
    return ""


def notify_session_dead():
    """X session 失效時打 worker → alertAdmin(web push 優先,無 LINE 額度問題)。"""
    tok = _read_token()
    if not tok:
        return
    body = json.dumps({"session_dead": True}).encode()
    req = urllib.request.Request(
        f"{WORKER}/political-ingest", data=body, method="POST",
        headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json",
                 "User-Agent": "political-watch/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            r.read()
        log("已通知 admin:X session 失效,請重登")
    except Exception as e:
        log(f"通知 admin 失敗:{str(e)[:100]}")


def main():
    if "--login" in sys.argv:
        scrape(login_mode=True)
        print("登入流程結束。之後直接跑 python3 watch_x.py 即可。")
        return 0
    st = load_state()
    posts = scrape()
    # session 健康度:撞登入牆=失效,通知 admin 一次(去重),恢復後重置旗標
    if STATUS["hit_login"]:
        if not st.get("dead_notified"):
            notify_session_dead()
            st["dead_notified"] = True
    elif STATUS["alive"] and st.get("dead_notified"):
        st.pop("dead_notified", None)
        log("session 已恢復")
    new = [p for p in posts if p["url"] not in st["seen"]]
    for p in new:
        st["seen"][p["url"]] = time.time()
    save_state(st)
    if not new:
        log("本輪無新貼文")
        return 0
    send(new, dry="--dry" in sys.argv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
