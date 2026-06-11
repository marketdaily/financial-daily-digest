"""政壇市場訊號 — 本機 Safari 掃描器(零成本、用既有 Safari 登入)。

透過 osascript 驅動使用者已登入的 Safari,在背景分頁依序開追蹤名單、抽貼文,
新貼文送 alert-worker /political-ingest → Claude 判讀市場關聯 → 既有 LINE 推播管線。
不搶焦點(不 activate Safari)。launchd 每 15 分鐘跑一次。

前置(一次性,已完成):Safari 設定 → 開發者 → 勾「允許來自 Apple Event 的 JavaScript」。

用法:
  python3 watch_safari.py          # 掃一輪+上送(launchd 用這個)
  python3 watch_safari.py --dry    # 掃+分析但不真推 LINE
"""
import json
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATE = HERE / "state.json"
LOG = HERE / "watch.log"
APPLESCRIPT = HERE / "scrape_safari.applescript"
WORKER = "https://marketdaily-alert-worker.delvin-12345678.workers.dev"

# 與 alert-worker/political_source.js、grok_political.py 同名單,改要三邊同步
HANDLES = [
    "realDonaldTrump", "WhiteHouse", "POTUS", "USTreasury", "scottbessent",
    "CommerceGov", "USTradeRep", "federalreserve", "SECGov", "elonmusk",
]
MAX_AGE_MIN = 75  # 只送這麼新的貼文(cron 15min,留重疊餘裕;worker 還有 48h 去重)


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
    cutoff = time.time() - 3 * 86400
    st["seen"] = {k: v for k, v in st["seen"].items() if v > cutoff}
    STATE.write_text(json.dumps(st))


def scrape():
    """回傳 [{handle,text,url,posted_at}]。osascript 驅動 Safari 背景分頁。"""
    try:
        out = subprocess.run(
            ["osascript", str(APPLESCRIPT), ",".join(HANDLES)],
            capture_output=True, text=True, timeout=240,
        )
    except subprocess.TimeoutExpired:
        log("osascript 逾時")
        return []
    if out.returncode != 0:
        log(f"osascript 失敗:{out.stderr.strip()[:160]}")
        return []
    posts = []
    for line in out.stdout.splitlines():
        if "\t" not in line:
            continue
        handle, payload = line.split("\t", 1)
        if payload.startswith("ERR:"):
            log(f"@{handle}: {payload[:80]}")
            continue
        try:
            items = json.loads(payload)
        except Exception:
            continue
        fresh = 0
        for it in items:
            try:
                ts = datetime.fromisoformat(it["time"].replace("Z", "+00:00"))
            except Exception:
                continue
            age = (datetime.now(timezone.utc) - ts).total_seconds() / 60
            if age > MAX_AGE_MIN:
                continue
            posts.append({"handle": handle, "text": it["text"][:600],
                          "url": it["url"], "posted_at": it["time"]})
            fresh += 1
        log(f"@{handle}: 頁面 {len(items)} 則,{MAX_AGE_MIN}min 內 {fresh} 則")
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
                 "User-Agent": "political-watch-safari/1.0"},
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        res = json.loads(r.read().decode())
    rep = res.get("report") or {}
    log(f"上送 {len(posts)} 則 → 分析 {res.get('analyzed')},訊號 {len(res.get('signals') or [])},"
        f"達標 {rep.get('qualified', 0)},推播 {rep.get('pushed', 0)}{'(dry)' if dry else ''}")
    for s in (res.get("signals") or []):
        log(f"  · sev{s['severity']} [{s['kind']}] {s['name_zh']}:{s['headline_zh'][:50]}")


def main():
    st = load_state()
    posts = scrape()
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
