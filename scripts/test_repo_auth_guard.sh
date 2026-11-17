#!/bin/bash
# 自測:用暫存 repo+暫存 log 目錄,不碰生產 repo/state
set -u
G="$(cd "$(dirname "$0")" && pwd)/repo_auth_guard.py"
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
pass=0; fail=0
chk(){ if [ "$1" = "$2" ]; then pass=$((pass+1)); else fail=$((fail+1)); echo "FAIL $3: want $1 got $2"; fi; }
git init -q "$T/origin.git" --bare; git clone -q "$T/origin.git" "$T/r" 2>/dev/null
cd "$T/r"; git config user.email t@t; git config user.name t
echo a>a; git add a; git commit -qm a; git push -q origin HEAD:main 2>/dev/null; git branch -q -u origin/main 2>/dev/null || git branch -q --set-upstream-to=origin/main
mkdir "$T/logs"
run(){ GUARD_REPO="$T/r" GUARD_LOG_DIRS="$T/logs" GUARD_STATE="$T/state.json" GUARD_NOW="${NOW:-$(date +%s)}" python3 "$G" >/dev/null; echo $?; }
chk 0 "$(run)" healthy
mkdir -p "$(git rev-parse --git-dir)/rebase-merge"; chk 2 "$(run)" rebase_stuck
chk 0 "$(run)" dedup_same_issue
NOW=$(( $(date +%s) + 13*3600 )) ; chk 2 "$(run)" realert_after_12h; unset NOW
rmdir "$(git rev-parse --git-dir)/rebase-merge"; chk 2 "$(run)" recovery_green
chk 0 "$(run)" healthy_again
echo "x OAuth session expired y" > "$T/logs/news_reactive_x.log"; chk 2 "$(run)" auth_expired
touch -d '5 hours ago' "$T/logs/news_reactive_x.log"; chk 2 "$(run)" auth_old_log_recovers
chk 0 "$(run)" healthy3
git checkout -q --detach; chk 2 "$(run)" detached; git checkout -q -; run >/dev/null
echo b>b; git add b; OLD="@$(( $(date +%s) - 18000 )) +0800"; GIT_COMMITTER_DATE="$OLD" git commit -qm b --date="$OLD"; chk 2 "$(run)" unpushed_old
git push -q origin HEAD:main 2>/dev/null; run >/dev/null
echo c>c; git add c; git commit -qm c; chk 0 "$(run)" unpushed_fresh_ok
echo "pass=$pass fail=$fail"; [ $fail = 0 ]
