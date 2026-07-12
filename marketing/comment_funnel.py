#!/usr/bin/env python3
"""IG 留言閘門漏斗:掃自家貼文的關鍵字留言,自動私訊訂閱連結(私訊失敗退公開回覆)。

設計源自 @100xengineers 拆解(memory reference_100xengineers_playbook):
value 貼文餵觸及,gated 貼文 caption 只寫「留言『早鳥』」,連結由本 bot 回。

用法:
    python comment_funnel.py          正常執行(winrig cron 每 10 分鐘)
    python comment_funnel.py --dry    只列會做的動作,不回覆不寫狀態

閘門貼文偵測:近 14 天自家 media,caption 含「留言」+已註冊關鍵字即視為 gated。
權限:公開回覆需 instagram_manage_comments;私訊需 instagram_manage_messages
(App Review advanced access 核准前私訊必失敗,自動退公開回覆)。缺 comments 權限
=整條漏斗死,推 admin 告警(24h 防重)後中止。
"""
import json
import sys
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from auto_post import GRAPH, http, load_env  # noqa: E402

STATE_FILE = HERE / "social_out" / "comment_funnel_state.json"
TW = timezone(timedelta(hours=8))
LOOKBACK_DAYS = 14
MAX_REPLIES_PER_RUN = 25

SUB_URL = "https://marketdaily.ai/?utm_source=ig&utm_medium=comment&utm_campaign=earlybird"
KEYWORDS = {
    "早鳥": {
        "dm": ("這是你的早鳥連結 👉 " + SUB_URL + "\n"
               "目前全功能限時免費開放;未來恢復收費後,現在訂閱的早鳥用戶"
               "永久保留免費使用權 ✌️"),
        "receipt": "已私訊你早鳥連結 📩 沒收到的話看一下訊息邀請匣",
        "public": ("早鳥連結在這 👉 " + SUB_URL + "\n"
                   "目前全功能限時免費;早鳥訂閱在未來恢復收費後永久保留免費使用權 ✌️"),
    },
}
KEYWORDS["earlybird"] = KEYWORDS["早鳥"]


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"replied": {}, "perm_alert_ts": "", "dm_available": None}


def save_state(state):
    replied = state["replied"]
    if len(replied) > 5000:
        state["replied"] = dict(sorted(replied.items(), key=lambda x: x[1])[-4000:])
    STATE_FILE.parent.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


def alert(env, msg, state, dedupe_hours=24):
    last = state.get("perm_alert_ts") or ""
    if last and datetime.now(TW) - datetime.fromisoformat(last) < timedelta(hours=dedupe_hours):
        return
    tok = env.get("MARKETDAILY_ALERT_TOKEN", "")
    if not tok:
        root_env = HERE.parent / ".env"
        if root_env.exists():
            for line in root_env.read_text(encoding="utf-8").splitlines():
                if line.startswith("MARKETDAILY_ALERT_TOKEN="):
                    tok = line.split("=", 1)[1].strip()
    if not tok:
        return
    worker = env.get("MARKETDAILY_ALERT_WORKER_URL",
                     "https://marketdaily-alert-worker.delvin-12345678.workers.dev")
    ok, _ = http(f"{worker.rstrip('/')}/internal/admin-line-push", "POST",
                 json_body={"message": msg},
                 headers={"Authorization": f"Bearer {tok}",
                          # 裸 urllib UA 會被 Cloudflare 1010 擋(2026-07-10 實測)
                          "User-Agent": "Mozilla/5.0 MarketDailyBot/1.0"})
    if ok:
        state["perm_alert_ts"] = datetime.now(TW).isoformat()


def paged_get(url, qtok, cap=200):
    items, nxt = [], f"{url}&access_token={qtok}"
    while nxt and len(items) < cap:
        ok, r = http(nxt)
        if not ok:
            return items, r
        items += r.get("data", [])
        nxt = (r.get("paging") or {}).get("next")
    return items, None


def gated_media(env, qtok):
    since = datetime.now(TW) - timedelta(days=LOOKBACK_DAYS)
    media, err = paged_get(
        f"{GRAPH}/{env['IG_USER_ID']}/media?fields=id,caption,timestamp,permalink&limit=25",
        qtok, cap=50)
    if err:
        print(f"  ⚠️ 讀 media 失敗:{err}")
        return []
    out = []
    for m in media:
        ts = datetime.fromisoformat(m["timestamp"].replace("+0000", "+00:00"))
        if ts < since.astimezone(timezone.utc):
            continue
        cap_text = m.get("caption") or ""
        if "留言" not in cap_text and "comment" not in cap_text.lower():
            continue
        kws = [k for k in KEYWORDS if k.lower() in cap_text.lower()]
        if kws:
            out.append((m, kws))
    return out


def match_keyword(text, kws):
    low = (text or "").lower()
    for k in kws:
        if k.lower() in low:
            return k
    return None


def private_reply(env, comment_id, text):
    ok, r = http(f"{GRAPH}/{env['FB_PAGE_ID']}/messages", "POST",
                 json_body={"recipient": {"comment_id": comment_id},
                            "message": {"text": text},
                            "access_token": env["META_ACCESS_TOKEN"]})
    return ok, r


def public_reply(env, comment_id, text):
    ok, r = http(f"{GRAPH}/{comment_id}/replies", "POST",
                 form={"message": text, "access_token": env["META_ACCESS_TOKEN"]})
    return ok, r


def is_permission_error(r):
    err = (r or {}).get("error", {})
    return isinstance(err, dict) and (err.get("code") in (3, 10, 200, 190)
                                      or "permission" in str(err.get("message", "")).lower())


def run(dry=False):
    env = load_env()
    qtok = urllib.parse.quote(env["META_ACCESS_TOKEN"])
    state = load_state()

    _, me = http(f"{GRAPH}/{env['IG_USER_ID']}?fields=username&access_token={qtok}")
    my_username = (me or {}).get("username", "")

    targets = gated_media(env, qtok)
    if not targets:
        print(f"[{datetime.now(TW):%F %T}] 近 {LOOKBACK_DAYS} 天無閘門貼文,無事可做")
        return 0

    replied_n, perm_dead = 0, False
    for m, kws in targets:
        comments, err = paged_get(
            f"{GRAPH}/{m['id']}/comments?fields=id,text,username,timestamp&limit=50", qtok)
        if err:
            if is_permission_error(err):
                perm_dead = True
                break
            print(f"  ⚠️ 讀留言失敗 {m['id']}:{err}")
            continue
        for c in comments:
            cid = c["id"]
            if cid in state["replied"] or c.get("username") == my_username:
                continue
            kw = match_keyword(c.get("text"), kws)
            if not kw:
                continue
            if replied_n >= MAX_REPLIES_PER_RUN:
                print("  ⏸ 本輪回覆上限已到,其餘留待下輪")
                break
            spec = KEYWORDS[kw]
            if dry:
                print(f"  [DRY] 會回 @{c.get('username')} on {m['permalink']} ({kw})")
                replied_n += 1
                continue
            sent_via = None
            if state.get("dm_available") is not False:
                ok, r = private_reply(env, cid, spec["dm"])
                if ok:
                    sent_via = "dm"
                    state["dm_available"] = True
                    ok2, _ = public_reply(env, cid, spec["receipt"])
                    if not ok2:
                        print(f"  ⚠️ DM 成功但公開回執失敗 {cid}")
                elif is_permission_error(r):
                    state["dm_available"] = False
                    print("  ℹ️ instagram_manage_messages 未開,本輪起退公開回覆")
                else:
                    print(f"  ⚠️ DM 失敗(非權限):{r}")
            if not sent_via:
                ok, r = public_reply(env, cid, spec["public"])
                if ok:
                    sent_via = "public"
                elif is_permission_error(r):
                    perm_dead = True
                    break
                else:
                    print(f"  ⚠️ 公開回覆失敗 {cid}:{r}")
                    continue
            state["replied"][cid] = datetime.now(TW).isoformat()
            replied_n += 1
            print(f"  ✅ {sent_via} → @{c.get('username')} ({kw})")
        if perm_dead:
            break

    if perm_dead and not dry:
        alert(env, "🚨 留言漏斗:回覆被 Meta 擋(權限碼)。token 已含 instagram_manage_comments"
                   "(標準存取),但對外公開粉絲的回覆/私訊需 Advanced access。"
                   "請到 App→Instagram use case 提 App Review 申請 advanced access"
                   "(需螢幕錄影+商家驗證),核准後把 marketing/.env 的 "
                   "COMMENT_FUNNEL_ADVANCED 設 1。", state)
    if not dry:
        save_state(state)
    print(f"[{datetime.now(TW):%F %T}] 閘門貼文 {len(targets)} 篇,本輪回覆 {replied_n} 則"
          f"{',⚠️ 權限缺失' if perm_dead else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(run(dry="--dry" in sys.argv))
