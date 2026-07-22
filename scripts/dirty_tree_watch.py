#!/usr/bin/env python3
"""git tracked 檔「長期髒」哨兵。

tracked 修改持續超過門檻小時數未 commit=疑似「孤兒 cron 輸出檔」(writer cron 沒有對應的
persist owner),會讓所有掛 cron_abort_if_dirty 守門的 runner 靜默略過整輪(2026-07-17 事故:
intel/signal_ledger.jsonl+scripts/buy_signal_log.json 髒 2 天,6 支 runner 餓死,
digest archive SEO 失守)。由 ~/.marketdaily-fallback/dirty_tree_watch_runner.sh 每日呼叫,
偵測器刻意獨立於受害 runner——不可被自己要偵測的條件擋掉。

exit 0=乾淨或髒齡未達門檻;exit 2=有檔案髒逾門檻(stdout 即告警文案);其他=自身故障。
"""
import json
import os
import subprocess
import sys
import time

REPO = os.environ.get("MD_REPO", os.path.expanduser("~/Delvin-agent"))
STATE = os.environ.get(
    "DIRTY_WATCH_STATE",
    os.path.expanduser("~/.marketdaily-fallback/state/dirty_tree_first_seen.json"))
THRESHOLD_H = float(os.environ.get("DIRTY_WATCH_THRESHOLD_H", "20"))


def dirty_tracked(repo):
    """回傳 tracked 且有未 commit 修改(M/A/D,不含 ??)的路徑。

    用 --porcelain -z(NUL 分隔、不做 C-style quoting)避免中文/空白檔名被引號包裹;
    --no-renames 讓 rename 退化為 D+A 單 token 條目——雙 token 格式(新\\0舊)曾在
    worktree rename(Y 欄 R,如 add -N 後 mv)且來源路徑首字為 R/C 時吞掉下一筆
    真髒檔=靜默漏報(2026-07-17 驗證者 F2)。skip 條件仍查 X+Y 兩欄當第二層防禦。
    """
    out = subprocess.run(
        ["git", "-C", repo, "status", "--porcelain", "-z", "--no-renames"],
        capture_output=True, check=True).stdout.decode("utf-8", "replace")
    toks = out.split("\0")
    paths, i = [], 0
    while i < len(toks):
        t = toks[i]
        if len(t) < 4:
            i += 1
            continue
        xy, path = t[:2], t[3:]
        if xy == "??":
            i += 1
            continue
        paths.append(path)
        i += 2 if ("R" in xy or "C" in xy) else 1
    return sorted(set(paths))


def main():
    now = int(float(os.environ.get("DIRTY_WATCH_NOW", time.time())))
    paths = dirty_tracked(REPO)

    old = {}
    if os.path.exists(STATE):
        try:
            with open(STATE, encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                old = {k: v for k, v in loaded.items() if isinstance(v, (int, float))}
        except (ValueError, OSError):
            old = {}  # 壞 state 當空重建,哨兵本身不可因 state 損毀而死

    state = {p: old.get(p, now) for p in paths}  # 已 commit 的自動掉出,重髒=重新計時
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = STATE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)
    os.replace(tmp, STATE)

    stale = {p: (now - t) / 3600 for p, t in state.items()
             if (now - t) >= THRESHOLD_H * 3600}
    if not stale:
        print(f"ok: {len(paths)} 檔髒中,皆未達 {THRESHOLD_H:g}h 門檻" if paths
              else "ok: tracked 全乾淨")
        return 0

    detail = "、".join(f"{p}({h:.0f}h)" for p, h in sorted(stale.items()))
    print(f"git tracked 檔持續髒逾{THRESHOLD_H:g}h:{detail}——期間 cron_abort_if_dirty(blanket)"
          f"與 scope 涵蓋這些檔的 scoped 守門 runner 略過中;若是人工 WIP 請知悉,"
          f"若是 cron 輸出檔=缺 persist owner"
          f"(writer 的 runner 用 cron_git_persist 收自己的輸出,參考 valuation_ledger_runner)")
    return 2


if __name__ == "__main__":
    sys.exit(main())
