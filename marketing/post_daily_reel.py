#!/usr/bin/env python3
"""發當日日報短影音 reel(冪等)。由 social_post_runner.sh 在各發文窗口呼叫。

用法: post_daily_reel.py [tw|us] [--dry]
  tw(預設)=台股晨報 reel,09:00 台股開盤前發(08:00-08:59 窗口)
  us=美股晚報 reel,21:30 TW 美股開盤前發(20:30-21:29 窗口)

exit code: 0=發出或已發過 / 2=今天沒有已驗證的 reel(生成端出問題) / 3=主平台全失敗
           4=主平台已發出但次要平台失敗(如 YT 帳號停權;2026-07-10 起 YT 默默失敗
           兩天沒人知道的教訓——非 skipped 的平台失敗不准無聲)
"""
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from auto_post import load_env, post_reel_direct
from daily_run import posted_ids

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "video_brief" / "out"


def main():
    dry = "--dry" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    edition = args[0] if args else "tw"
    if edition not in ("tw", "us"):
        sys.exit(f"未知 edition「{edition}」,只接受 tw/us")
    today = datetime.now().strftime("%Y-%m-%d")
    src = OUT / f"post_{today}_{edition}.json"
    if not src.exists():
        # 與生成端共用同一事實源:當日(該版本)日報 archive 存在才該有 reel
        # (週日/假日沒日報→兩端同步靜默,不會再有規則岔開的假警報)
        suffix = "_us" if edition == "us" else ""
        digest = ROOT / "docs" / "output" / f"digest_{today}{suffix}.html"
        if not digest.exists():
            print(f"今天沒有日報 archive({digest.name}),照設計不該有 reel,靜默跳過")
            return
        print(f"⚠️ 找不到 {src.name} —— 今天沒有已驗證的 reel")
        sys.exit(2)
    post = json.loads(src.read_text(encoding="utf-8"))
    if not post.get("verified"):
        print("⚠️ post json 未通過驗證,不發")
        sys.exit(2)
    if post["id"] in posted_ids():
        print(f"已發過 {post['id']},無動作")
        return
    if dry:
        print(f"[dry] 將發 {post['id']} → {', '.join(post['platforms'])}")
        print(post["video_url"])
        print(post["caption"])
        return
    results = post_reel_direct(load_env(), post["id"], post["video_url"],
                               post["caption"], post["platforms"])
    primary = [r for p, r in results.items() if p in ("instagram", "facebook")]
    if primary and not any(r["ok"] for r in primary):
        sys.exit(3)
    failed = [p for p, r in results.items() if not r["ok"] and not r.get("skipped")]
    if failed:
        print(f"⚠️ 次要平台失敗:{', '.join(failed)}(主平台已發出)")
        sys.exit(4)


if __name__ == "__main__":
    main()
