#!/usr/bin/env python3
"""每日自動發文 —— 依 social_posts.json 順序,每次發下一篇還沒發過的貼文。

由 winrig cron `social_post_runner.sh` 執行(週一/三/五 14:00 TW);也可手動:
    python daily_run.py            發下一篇(過閘才發)
    python daily_run.py --dry      只顯示下一篇會發什麼,不實際發、不改任何檔
    python daily_run.py --gate-only 只跑閘門(退場/待覆核/告警都會真的落地),不發文

2026-08-03 起每一則發文前都要過 `post_gate`:marketing/CLAUDE.md 的鐵則「發前必逐字驗
caption」本來只是寫給人看的,但真正在發文的是 cron。實測那天佇列頭是 `tldr_2026-07-22_us`,
再兩天就會公開發出 12 天前的市場脈搏數據。閘門把那條鐵則變成機器動作。
"""
import json
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import post_gate  # noqa: E402
from auto_post import (LOG_FILE, POSTS_FILE, cmd_post, http, load_env,  # noqa: E402
                       load_posts)

STATE_FILE = Path(__file__).parent / "social_out" / "post_gate_state.json"


def posted_ids():
    """已成功發過(任一平台成功即算)的貼文 id。"""
    ids = set()
    if LOG_FILE.exists():
        for line in LOG_FILE.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if any(v.get("ok") for v in (rec.get("results") or {}).values()):
                ids.add(rec.get("post"))
    return ids


def push_admin(message: str) -> None:
    """閘門擋下東西一定要有人知道。推不出去就印出來,絕不無聲。"""
    try:
        tok = post_gate.resolve_alert_token()
        if not tok:
            print("  ⚠️ 無 MARKETDAILY_ALERT_TOKEN(repo 根 .env),閘門告警只留在 log")
            return
        ok, resp = http(post_gate.alert_endpoint(), "POST",
                        json_body={"message": message},
                        headers={"Authorization": f"Bearer {tok}",
                                 # 裸 urllib UA 會被 Cloudflare 擋(2026-07-10 實測)
                                 "User-Agent": "Mozilla/5.0 MarketDailyBot/1.0"})
        if not ok:
            print(f"  ⚠️ 閘門告警推播失敗:{resp}")
    except Exception as e:  # noqa: BLE001
        print(f"  ⚠️ 閘門告警推播例外:{e}")


def main():
    dry = "--dry" in sys.argv
    gate_only = "--gate-only" in sys.argv
    print(f"[{datetime.now():%Y-%m-%d %H:%M}] daily_run")
    done = posted_ids()
    now = date.today()

    try:
        nxt, blocked = post_gate.pick_postable(load_posts(), now, done)
    except Exception as e:  # noqa: BLE001
        # fail-closed:閘門自己壞掉時不發文(未經檢查的內容出去比停一天貴)
        msg = f"🚦 社群發文閘門自己出錯,今天不發:{type(e).__name__}: {e}"
        print(f"  ❌ {msg}")
        if not dry:
            push_admin(msg)
        return

    for v in blocked:
        print(f"  ⛔ 擋下 {v.post_id}({v.status}) — {v.reason_text()}")

    if dry:
        print(f"  [dry] 下一篇:{nxt['id']} → {', '.join(nxt['platforms'])}" if nxt
              else "  [dry] 沒有任何過閘的貼文可發。")
        return

    if blocked:
        try:
            result = post_gate.apply_verdicts(POSTS_FILE, STATE_FILE, blocked, now)
            print(f"  閘門落地:自動退場 {len(result['retired'])} / 待覆核 {len(result['needs_review'])}")
            if result["alert_ids"]:
                push_admin(post_gate.format_alert(result, blocked, nxt["id"] if nxt else None))
        except Exception as e:  # noqa: BLE001
            # 落地層壞掉不該連累「今天該發的那則」——判決本身已經算出來了,擋的照擋。
            print(f"  ⚠️ 閘門落地失敗(判決仍生效,只是沒寫進檔案):{type(e).__name__}: {e}")
            push_admin(f"🚦 社群發文閘門落地層失敗:{type(e).__name__}: {e}")

    if not nxt:
        print("  沒有任何過閘的貼文可發 —— 無動作。")
        return
    if gate_only:
        print(f"  [gate-only] 閘門已落地;下一則可發是 {nxt['id']}(本次不發文)")
        return
    print(f"  發布:{nxt['id']}")
    cmd_post(load_env(), nxt["id"])


if __name__ == "__main__":
    main()
