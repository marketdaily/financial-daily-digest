"""adcreative 佇列衛生:草稿超過 STALE_DAYS 未發自動標 retired(生成時事實可能過期)。

發文唯一源 daily_run 一天只發一篇品牌貼文,佇列裡的 adcreative 常排到數週後才輪到,
但草稿事實(方案/戰績/市況)是生成當下驗證的——放太久=陳舊風險。標 retired 不硬刪
(social_posts.json 欄位慣例:硬刪會被 promote_* 殭屍回填)。

用法:
  python queue_hygiene.py          # 執行退役+印報告
  python queue_hygiene.py --dry    # 只看不改
  python queue_hygiene.py --stock  # 只印新鮮未發 adcreative 數(給 shell 動態節流用)
"""
import json
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from auto_post import POSTS_FILE
from daily_run import posted_ids

STALE_DAYS = 14


def _draft_date(pid):
    m = re.match(r"adcreative_(\d{4}-\d{2}-\d{2})_", pid)
    return date.fromisoformat(m.group(1)) if m else None


def main():
    dry = "--dry" in sys.argv
    stock_only = "--stock" in sys.argv
    data = json.loads(POSTS_FILE.read_text(encoding="utf-8"))
    posts = data["posts"] if isinstance(data, dict) else data
    done = posted_ids()
    today = date.today()
    fresh, stale = 0, []
    for p in posts:
        pid = str(p.get("id", ""))
        d = _draft_date(pid)
        if d is None or pid in done or p.get("retired"):
            continue
        if (today - d).days > STALE_DAYS:
            stale.append(p)
        else:
            fresh += 1
    if stock_only:
        print(fresh)
        return
    if stale and not dry:
        for p in stale:
            p["retired"] = f"stale>{STALE_DAYS}d 自動退役(queue_hygiene {today}):生成時事實可能已過期"
        POSTS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[queue_hygiene] 新鮮未發 adcreative:{fresh} 則;退役:{len(stale)} 則"
          f" {[p['id'] for p in stale]}{'(dry)' if dry else ''}")


if __name__ == "__main__":
    main()
