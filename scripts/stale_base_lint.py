#!/usr/bin/env python3
"""過期底稿覆寫守衛:工作樹裡某個檔案是不是「舊版本 + 小修」而不是「HEAD + 小修」。

2026-07-30 事故(同形狀當天第二次):某 session 拿 commit 882e67b 的**父版** intel/patrol.py
當底稿整檔寫回,只為了加 2 行 chart_facts,結果把當天 01:22 才上線的 us_congress_trades +
gold_macro 兩個連接器整條抹掉。兩者原本都包在 try/except「不擋巡邏」裡,所以夜巡不會報錯,
只會靜默少兩個信源。同一天早上 sync.sh 也是拿過期目錄覆蓋記憶。

為什麼不用「刪掉了最近才 commit 的行」當判準:那會天天誤報——正常開發本來就一直在改自己
剛寫的東西。真正的指紋是**工作樹內容離某個祖先版本比離 HEAD 更近**:正常編輯永遠是
HEAD+小差異,拿舊底稿覆寫才會出現「對 HEAD 差 23 行、對某祖先只差 3 行」。

exit 1 = 有可疑檔案(呼叫端負責推播);exit 0 = 乾淨。
"""
from __future__ import annotations

import os
import subprocess
import sys

REPO = os.environ.get("MD_REPO") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HISTORY_DEPTH = 12
MAX_BYTES = 2_000_000


def git(*args: str, binary: bool = False):
    r = subprocess.run(
        ["git", "-C", REPO, *args],
        capture_output=True,
        check=False,
    )
    if r.returncode != 0:
        return None
    return r.stdout if binary else r.stdout.decode("utf-8", "replace")


def modified_files() -> list[str]:
    out = git("diff", "--name-only", "HEAD")
    return [p for p in (out or "").splitlines() if p.strip()]


def changed_lines(blob: bytes, worktree_path: str) -> int | None:
    """blob 與工作樹檔案之間有多少行不同(新增+刪除)。None = 無法比較(二進位/讀不到)。"""
    try:
        with open(os.path.join(REPO, worktree_path), "rb") as f:
            cur = f.read()
    except OSError:
        return None
    if b"\0" in blob[:8000] or b"\0" in cur[:8000]:
        return None
    if len(blob) > MAX_BYTES or len(cur) > MAX_BYTES:
        return None
    import difflib

    a = blob.decode("utf-8", "replace").splitlines()
    b = cur.decode("utf-8", "replace").splitlines()
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    diff = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag != "equal":
            diff += (i2 - i1) + (j2 - j1)
    return diff


def history_blobs(path: str) -> list[tuple[str, bytes]]:
    """該檔在 HEAD 之前的歷史版本(去重、新→舊),不含 HEAD 當前內容。"""
    out = git("log", f"-n{HISTORY_DEPTH}", "--format=%H", "--", path)
    blobs: list[tuple[str, bytes]] = []
    seen: set[bytes] = set()
    head_blob = git("show", f"HEAD:{path}", binary=True)
    if head_blob is not None:
        seen.add(head_blob)
    for sha in (out or "").splitlines():
        sha = sha.strip()
        if not sha:
            continue
        for ref in (f"{sha}:{path}", f"{sha}^:{path}"):
            b = git("show", ref, binary=True)
            if b is None or b in seen:
                continue
            seen.add(b)
            blobs.append((ref.split(":")[0], b))
    return blobs


def scan() -> list[str]:
    findings = []
    for path in modified_files():
        head_blob = git("show", f"HEAD:{path}", binary=True)
        if head_blob is None:
            continue  # 新檔,沒有 HEAD 版本可比
        d_head = changed_lines(head_blob, path)
        if d_head is None or d_head == 0:
            continue
        best = None
        for ref, blob in history_blobs(path):
            d_old = changed_lines(blob, path)
            if d_old is None:
                continue
            if best is None or d_old < best[1]:
                best = (ref, d_old)
        if best and _is_stale_base(best[1], d_head, path):
            findings.append(
                f"{path}: 對 HEAD 差 {d_head} 行,但對舊版 {best[0]} 只差 {best[1]} 行"
                f" → 疑似拿過期底稿整檔覆寫,HEAD 之後的改動可能被抹掉"
            )
    return findings


def _small_edit_budget(path: str) -> int:
    """「小修」的行數上限:30 行或檔案 5%(取大者)。"""
    try:
        with open(os.path.join(REPO, path), "rb") as f:
            n = f.read().count(b"\n") + 1
    except OSError:
        n = 0
    return max(30, n // 20)


def _is_stale_base(d_old: int, d_head: int, path: str) -> bool:
    """本守衛主張的是「有人拿舊版當底稿,只做了小修就寫回」。三個條件都要成立:

    1. 對舊版比對 HEAD 近 —— 基本方向。
    2. 近得夠明顯(至少一半)—— 兩者接近時排序只是雜訊。
    3. **對舊版的差異本身要小** —— 這條是 2026-07-30 上線當天被自己誤判逼出來的:
       `marketing/ad_creative_drafts.json` 是每週整檔重生的批次檔,新批次對 HEAD 差 663 行、
       對某祖先差 533 行,只因兩份都很大而排序偶然反過來就被判紅。但「差 533 行」根本不是
       「小修」,主張不成立。沒有這條絕對上限,所有整檔重生的產出檔(批次 JSON、快照、
       重新渲染的資料)都會定期假紅 → 警報疲勞,守衛失去意義。
    """
    if d_old >= d_head:
        return False
    if d_old * 2 > d_head:
        return False
    return d_old <= _small_edit_budget(path)


def main() -> int:
    findings = scan()
    if not findings:
        print("✅ 過期底稿守衛:工作樹的每個改動檔都以 HEAD 為底稿")
        return 0
    print(f"✗ 疑似過期底稿覆寫 {len(findings)} 檔:")
    for f in findings:
        print(f"  - {f}")
    print("  處理:git diff <檔> 確認有沒有非預期的刪除;要救就 git checkout HEAD -- <檔> 後重貼你真正的修改")
    return 1


if __name__ == "__main__":
    sys.exit(main())
