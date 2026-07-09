#!/usr/bin/env python3
"""每日自動發文 —— 依 social_posts.json 順序,每次發下一篇還沒發過的貼文。

由 launchd 每天執行一次;也可手動:
    python daily_run.py          發下一篇
    python daily_run.py --dry    只顯示下一篇會發什麼,不實際發
"""
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from auto_post import LOG_FILE, cmd_post, load_env, load_posts


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


def main():
    dry = "--dry" in sys.argv
    print(f"[{datetime.now():%Y-%m-%d %H:%M}] daily_run")
    done = posted_ids()
    nxt = next((p for p in load_posts()
                if p["id"] not in done and not p.get("retired")), None)
    if not nxt:
        print("  所有貼文都發完了 —— 無動作。")
        return
    if dry:
        print(f"  [dry] 下一篇:{nxt['id']} → {', '.join(nxt['platforms'])}")
        return
    print(f"  發布:{nxt['id']}")
    cmd_post(load_env(), nxt["id"])


if __name__ == "__main__":
    main()
