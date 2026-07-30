"""Overfit Check r/algotrading 市場驗證自動監控。

launchd 每日兩次:登入態 Chrome profile 查三則留言的分數/回覆/是否被刪 + 收件匣,
與 monitor_state.json 差分,有新動靜推播 admin(alert-worker web push)並記 monitor_log.md。
2026-07-15 後仍零互動 → 發一次「驗證無訊號」總結後停。
"""
import json
import sys
import time
import urllib.request
from datetime import date
from pathlib import Path

BASE = Path(__file__).parent
STATE = BASE / "monitor_state.json"
LOG = BASE / "monitor_log.md"
PROFILE = Path.home() / ".overfit_check_profile"
ENV = BASE.parent.parent / ".env"
WORKER = "https://marketdaily-alert-worker.delvin-12345678.workers.dev/internal/admin-line-push"
VERDICT_DATE = date(2026, 7, 15)

COMMENTS = {
    "t1_ow8od3z": "USTEC Fibo 帖",
    "t1_ow8pync": "1682% 回報帖",
    "t1_ow8rkj4": "回測可信度提問帖",
}
PERMALINKS = {
    "t1_ow8od3z": "/r/algotrading/comments/1ukgzs3/comment/ow8od3z/",
    "t1_ow8pync": "/r/algotrading/comments/1uknolw/comment/ow8pync/",
    "t1_ow8rkj4": "/r/algotrading/comments/1u2js33/comment/ow8rkj4/",
}


def alert_token():
    for line in ENV.read_text().splitlines():
        if line.startswith("MARKETDAILY_ALERT_TOKEN="):
            return line.split("=", 1)[1].strip()
    return None


def push_admin(text):
    token = alert_token()
    if not token:
        return
    req = urllib.request.Request(
        WORKER,
        data=json.dumps({"message": text[:4900]}).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {token}",
                 "User-Agent": "Mozilla/5.0 (overfit-check-monitor)"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=20)
    except Exception as e:
        print(f"push failed: {e}", file=sys.stderr)


def fetch_all():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(PROFILE), channel="chrome", headless=False,
            args=["--disable-blink-features=AutomationControlled",
                  "--window-position=-32000,-32000", "--window-size=1200,800"])
        page = ctx.new_page()
        page.goto("https://www.reddit.com/", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(4000)

        def get_json(url):
            return page.evaluate(
                """async (u) => { const r = await fetch(u, {credentials:'include'});
                   if (!r.ok) return {__err: r.status};
                   return await r.json(); }""", url)

        me = get_json("https://www.reddit.com/api/me.json")
        if not (isinstance(me, dict) and me.get("data", {}).get("name")):
            ctx.close()
            return {"error": "session_lost"}

        result = {"comments": {}, "inbox": []}
        mine = get_json("https://www.reddit.com/user/VINIO1107/comments.json?limit=20")
        listing = {c["data"]["name"]: c["data"]
                   for c in mine.get("data", {}).get("children", [])}
        for cid, label in COMMENTS.items():
            d = listing.get(cid)
            entry = {"label": label, "found": bool(d)}
            if d:
                entry.update(score=d.get("score"), removed=bool(d.get("removed")))
                tree = get_json(f"https://www.reddit.com{PERMALINKS[cid]}.json?raw_json=1")
                replies = 0
                if isinstance(tree, list) and len(tree) > 1:
                    try:
                        node = tree[1]["data"]["children"][0]["data"]
                        rep = node.get("replies")
                        if isinstance(rep, dict):
                            replies = len(rep["data"]["children"])
                    except (KeyError, IndexError, TypeError):
                        pass
                entry["replies"] = replies
            result["comments"][cid] = entry
            page.wait_for_timeout(1500)

        inbox = get_json("https://www.reddit.com/message/inbox.json?limit=25")
        for c in inbox.get("data", {}).get("children", []):
            d = c["data"]
            result["inbox"].append({
                "id": d.get("name"), "kind": c.get("kind"),
                "author": d.get("author"), "new": bool(d.get("new")),
                "subject": (d.get("subject") or "")[:60],
                "body": (d.get("body") or "")[:200],
            })
        ctx.close()
        return result


def main():
    state = json.loads(STATE.read_text()) if STATE.exists() else {
        "seen_inbox": [], "scores": {}, "replies": {}, "ever_engaged": False,
        "verdict_sent": False}
    now = time.strftime("%Y-%m-%d %H:%M")
    data = fetch_all()

    if data.get("error"):
        push_admin(f"⚠️ Overfit Check 監控:Reddit session 失效({data['error']}),需重新登入")
        return

    events = []
    for cid, e in data["comments"].items():
        if not e["found"]:
            events.append(f"❌ {e['label']} 留言消失(可能被移除)")
            continue
        if e.get("removed"):
            events.append(f"❌ {e['label']} 被標記 removed")
        old_r = state["replies"].get(cid, 0)
        if e.get("replies", 0) > old_r:
            events.append(f"💬 {e['label']} 新回覆 +{e['replies'] - old_r}(共 {e['replies']})")
            state["ever_engaged"] = True
        state["replies"][cid] = e.get("replies", old_r)
        state["scores"][cid] = e.get("score")

    for m in data["inbox"]:
        if m["id"] in state["seen_inbox"]:
            continue
        state["seen_inbox"].append(m["id"])
        tag = "📩 私訊" if m["kind"] == "t4" else "💬 回覆通知"
        events.append(f"{tag} from u/{m['author']}:{m['subject']} — {m['body'][:120]}")
        state["ever_engaged"] = True

    if events:
        scores = " / ".join(f"{e['label']}:{e.get('score', '?')}分"
                            for e in data["comments"].values() if e["found"])
        push_admin("🎣 Overfit Check Reddit 有動靜!\n" + "\n".join(events[:6])
                   + f"\n目前分數:{scores}")
    elif (date.today() >= VERDICT_DATE and not state["ever_engaged"]
          and not state["verdict_sent"]):
        push_admin("📉 Overfit Check 驗證結案:7 天零互動(無回覆/無DM/無問價),"
                   "建議收掉此點子,詳見 quant_lab/overfit_check/monitor_log.md")
        state["verdict_sent"] = True

    with LOG.open("a") as f:
        f.write(f"\n## {now}\n")
        for cid, e in data["comments"].items():
            f.write(f"- {e['label']}: score={e.get('score')} replies={e.get('replies')}"
                    f" removed={e.get('removed')} found={e['found']}\n")
        f.write(f"- inbox 未讀新項: {len(events)} 事件: {events or '無'}\n")

    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1))
    print(f"{now} ok, events={len(events)}")


if __name__ == "__main__":
    main()
