"""winrig 兩個靜默失效的哨兵(2026-11-17 建)。

事故:①git 卡在未完成的 pull --rebase 11 天(11/06–11/17)+本機 main 有 116 個排程 commit
從 10/24 起沒推上 origin,帳本資料只活在一顆磁碟;②claude -p 的 OAuth 10/30 起過期 16 天,
newsroom/news_reactive 每天失敗。兩件都零告警。

exit 0=健康 / 2=有問題(runner 推播) / 其他=哨兵自身故障。
只在狀態轉變或持續 12 小時時重推;恢復時推一則 🟢。
"""
import json, os, subprocess, sys, time
from pathlib import Path

REPO = Path(os.environ.get("GUARD_REPO", Path.home() / "Delvin-agent"))
LOG_DIRS = [Path(p) for p in os.environ.get("GUARD_LOG_DIRS", ":".join([
    str(Path.home() / "Delvin-agent/logs"),
    str(Path.home() / ".marketdaily-fallback/logs"),
    str(Path.home() / ".marketdaily-fallback"),
    str(Path.home() / "autonomous/logs"),
])).split(":") if p]
STATE = Path(os.environ.get("GUARD_STATE", Path.home() / ".marketdaily-fallback/state/repo_auth_guard.json"))
NOW = float(os.environ.get("GUARD_NOW", time.time()))
UNPUSHED_MAX_H = 3
AUTH_WINDOW_H = 2
REALERT_H = 12
AUTH_MARKERS = ("OAuth session expired", "Failed to authenticate", "Please run /login", "Invalid API key")


def git(*a):
    return subprocess.run(["git", "-C", str(REPO), *a], capture_output=True, text=True)


def repo_issues():
    out = []
    for d in ("rebase-merge", "rebase-apply"):
        p = git("rev-parse", "--git-path", d).stdout.strip()
        if p and (REPO / p if not os.path.isabs(p) else Path(p)).exists():
            out.append(f"git 卡在未完成的 rebase({d})")
    if git("symbolic-ref", "-q", "HEAD").returncode != 0:
        out.append("git HEAD 脫離分支(detached)")
    r = git("log", "--format=%ct", "@{u}..HEAD")
    if r.returncode != 0:
        r = git("log", "--format=%ct", "origin/main..HEAD")
    ts = [int(x) for x in r.stdout.split() if x.strip().isdigit()]
    if ts:
        age_h = (NOW - min(ts)) / 3600
        if age_h > UNPUSHED_MAX_H:
            out.append(f"{len(ts)} 個 commit 未推上 origin,最舊已 {age_h:.0f} 小時")
    return out


def auth_issues():
    cutoff = NOW - AUTH_WINDOW_H * 3600
    hits = []
    for d in LOG_DIRS:
        if not d.is_dir():
            continue
        for f in d.iterdir():
            try:
                if not f.is_file() or f.stat().st_mtime < cutoff or f.stat().st_size > 50_000_000:
                    continue
                with open(f, "rb") as fh:
                    fh.seek(max(0, f.stat().st_size - 400_000))
                    tail = fh.read().decode("utf-8", "ignore")
                if any(m in tail for m in AUTH_MARKERS):
                    hits.append(f.name)
            except OSError:
                continue
    if hits:
        return [f"claude -p 登入失效(近 {AUTH_WINDOW_H}h {len(hits)} 份 log 出現認證錯誤,例:{', '.join(sorted(hits)[:3])});請在 winrig 執行 claude /login"]
    return []


def main():
    issues = repo_issues() + auth_issues()
    prev = json.loads(STATE.read_text()) if STATE.exists() else {}
    fp = "|".join(sorted(i.split("(")[0].split(",")[0] for i in issues))
    STATE.parent.mkdir(parents=True, exist_ok=True)
    if not issues:
        STATE.write_text(json.dumps({"fp": "", "at": NOW}))
        if prev.get("fp"):
            print("🟢 [winrig] repo/登入 哨兵:已恢復正常")
            return 2
        print("ok")
        return 0
    if fp == prev.get("fp") and NOW - prev.get("at", 0) < REALERT_H * 3600:
        print("持續中(已告警過):" + ";".join(issues))
        return 0
    STATE.write_text(json.dumps({"fp": fp, "at": NOW}))
    print("🔴 repo/登入 哨兵:" + ";".join(issues))
    return 2


if __name__ == "__main__":
    sys.exit(main())
