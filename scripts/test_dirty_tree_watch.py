#!/usr/bin/env python3
"""dirty_tree_watch.py 迴歸測試(2026-07-17 孤兒 cron 輸出檔餓死 cron 生態鏈事故偵測器)。

隔離 temp git repo 實測,不碰真實 repo;時間全用 DIRTY_WATCH_NOW 注入(不寫死「今天」)。
用法: .venv/bin/python scripts/test_dirty_tree_watch.py   (exit 0=全過)
"""
import json
import os
import subprocess
import sys
import tempfile

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dirty_tree_watch.py")
H = 3600


def git(repo, *args):
    subprocess.run(["git", "-C", repo, "-c", "user.name=t", "-c", "user.email=t@t",
                    *args], check=True, capture_output=True)


def run_watch(repo, state, now, threshold_h="20"):
    env = dict(os.environ,
               MD_REPO=repo, DIRTY_WATCH_STATE=state,
               DIRTY_WATCH_NOW=str(now), DIRTY_WATCH_THRESHOLD_H=threshold_h)
    p = subprocess.run([sys.executable, SCRIPT], env=env, capture_output=True, text=True)
    return p.returncode, p.stdout.strip()


def main():
    fails = []

    def check(name, cond, detail=""):
        mark = "✅" if cond else "❌"
        print(f"{mark} {name}" + (f"  [{detail}]" if detail and not cond else ""))
        if not cond:
            fails.append(name)

    with tempfile.TemporaryDirectory() as tmp:
        repo = os.path.join(tmp, "repo")
        os.makedirs(repo)
        git(repo, "init", "-q")
        for name in ("a.txt", "b.txt", "my file.txt"):
            with open(os.path.join(repo, name), "w") as f:
                f.write("base\n")
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", "init")
        state = os.path.join(tmp, "state.json")
        t0 = 1_000_000_000

        # 1. 乾淨樹 → exit 0,state 空
        rc, out = run_watch(repo, state, t0)
        check("1 乾淨樹 exit 0", rc == 0, f"rc={rc} out={out}")
        check("1b state 為空 dict", json.load(open(state)) == {})

        # 2. tracked 檔剛髒 → exit 0(未達門檻),state 以 now 起錨
        with open(os.path.join(repo, "a.txt"), "a") as f:
            f.write("dirt\n")
        rc, out = run_watch(repo, state, t0)
        check("2 新髒未達門檻 exit 0", rc == 0, f"rc={rc}")
        check("2b first_seen=now", json.load(open(state)).get("a.txt") == t0)

        # 3. 21h 後仍髒 → exit 2,訊息含路徑+髒齡+機制名
        rc, out = run_watch(repo, state, t0 + 21 * H)
        check("3 髒逾20h exit 2", rc == 2, f"rc={rc}")
        check("3b 訊息含路徑與髒齡", "a.txt(21h)" in out, out)
        check("3c 訊息含 cron_abort_if_dirty", "cron_abort_if_dirty" in out)
        check("3d first_seen 不被重置", json.load(open(state)).get("a.txt") == t0)

        # 4. untracked 新檔不觸發(?? 排除)
        git(repo, "checkout", "--", "a.txt")
        with open(os.path.join(repo, "untracked.txt"), "w") as f:
            f.write("x\n")
        rc, out = run_watch(repo, state, t0 + 22 * H)
        check("4 只剩 untracked exit 0", rc == 0, f"rc={rc} out={out}")
        check("4b 已乾淨檔自 state 掉出", json.load(open(state)) == {})

        # 5. 重髒=重新計時(不沿用已掉出的舊 first_seen)
        with open(os.path.join(repo, "a.txt"), "a") as f:
            f.write("dirt2\n")
        rc, out = run_watch(repo, state, t0 + 30 * H)
        check("5 重髒重新計時 exit 0", rc == 0, f"rc={rc}")
        check("5b first_seen=新 now", json.load(open(state)).get("a.txt") == t0 + 30 * H)

        # 6. 壞 state JSON → 不 crash,當空重建
        with open(state, "w") as f:
            f.write("{corrupted")
        rc, out = run_watch(repo, state, t0 + 31 * H)
        check("6 壞 state 不 crash exit 0", rc == 0, f"rc={rc}")
        check("6b state 重建", json.load(open(state)).get("a.txt") == t0 + 31 * H)

        # 7. 空白檔名(-z 無 quoting):先起錨一輪,20h 後過門檻報警
        with open(os.path.join(repo, "my file.txt"), "a") as f:
            f.write("dirt\n")
        rc, out = run_watch(repo, state, t0 + 32 * H)
        check("7 空白檔名起錨輪 exit 0", rc == 0, f"rc={rc} out={out}")
        rc, out = run_watch(repo, state, t0 + 53 * H)
        check("7b 空白檔名 stale 報警 exit 2", rc == 2, f"rc={rc}")
        check("7c 訊息含空白檔名", "my file.txt(21h)" in out, out)

        # 8. rename(staged R)不 crash 且追蹤新路徑
        git(repo, "checkout", "--", "a.txt", "my file.txt")
        git(repo, "mv", "b.txt", "c.txt")
        rc, out = run_watch(repo, state, t0 + 61 * H)
        check("8 rename 不 crash exit 0", rc == 0, f"rc={rc} out={out}")
        check("8b 追蹤新路徑 c.txt", "c.txt" in json.load(open(state)))

        # 9. 門檻可由環境變數覆寫
        rc, out = run_watch(repo, state, t0 + 61 * H, threshold_h="0")
        check("9 門檻=0 立即 stale exit 2", rc == 2, f"rc={rc}")

        # 10. worktree rename(add -N 後 mv,來源路徑首字 R)不吞下一筆真髒檔
        #     (2026-07-17 驗證者 F2:舊解析 "README.md" 首字 R 誤觸 i+=2,
        #      ` M zz_real_dirty.txt` 從監控中靜默消失)
        git(repo, "commit", "-qm", "collect staged rename")
        for name in ("README.md", "zz_real_dirty.txt"):
            with open(os.path.join(repo, name), "w") as f:
                f.write("base\n")
        git(repo, "add", "README.md", "zz_real_dirty.txt")
        git(repo, "commit", "-qm", "add f2 fixtures")
        os.rename(os.path.join(repo, "README.md"), os.path.join(repo, "RENAMED.md"))
        git(repo, "add", "-N", "RENAMED.md")
        with open(os.path.join(repo, "zz_real_dirty.txt"), "a") as f:
            f.write("dirt\n")
        rc, out = run_watch(repo, state, t0 + 70 * H)
        st = json.load(open(state))
        check("10 真髒檔不被 rename 條目吞掉", "zz_real_dirty.txt" in st, str(st))
        # 垃圾條目判定用精確集合相等,不用子字串("README.md" 含 "DME"=beekeeper 坑)
        check("10b state 恰為三合法檔零垃圾",
              set(st) == {"README.md", "RENAMED.md", "zz_real_dirty.txt"}, str(st))

        # 11. CJK 檔名(-z 無 C-quoting)正確追蹤與報警
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", "collect f2 fixtures")
        cjk = "中文 檔名.txt"
        with open(os.path.join(repo, cjk), "w") as f:
            f.write("base\n")
        git(repo, "add", cjk)
        git(repo, "commit", "-qm", "add cjk")
        with open(os.path.join(repo, cjk), "a") as f:
            f.write("dirt\n")
        rc, out = run_watch(repo, state, t0 + 80 * H)
        check("11 CJK 檔名起錨", json.load(open(state)).get(cjk) == t0 + 80 * H)
        rc, out = run_watch(repo, state, t0 + 101 * H)
        check("11b CJK 檔名報警含原名", rc == 2 and f"{cjk}(21h)" in out, out)

    print(f"\n{'全部通過' if not fails else '失敗: ' + ', '.join(fails)}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
