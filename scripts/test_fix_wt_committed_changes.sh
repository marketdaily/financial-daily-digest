#!/bin/bash
# cron_fix_wt_* 的「代理把修復 commit 進 worktree」路徑 —— 兩個方向都量。
#
# ⭐⭐ 2026-08-24 實鍋(老闆本人連兩班收到閹割備援版的真正原因):
#   digest_fix_playbook.md 第 5 步明寫叫自癒代理 `git commit`,而 guard 的
#   cron_fix_wt_changes 只讀 `git status`(=未 commit 的改動)。代理照著 playbook 做
#   ⇒ working tree 乾淨 ⇒ CHANGED 空 ⇒ verdict=none「代理判斷無法安全修復」
#   ⇒ 整包銷毀。那天的修復其實 49/49 綠、gate 9/9 綠,卻只剩一顆懸空 commit。
#   兩個半邊守同一件事卻用不同語意,而**從上線至今沒有任何東西在驗這條路徑**。
#
# 本測試用真 git repo 實跑 lib 本人(不手刻第二份判準),四個方向:
#   ① 代理 commit  → 看得到(修好前必紅)
#   ② 代理沒 commit → 看得到(舊行為不可回歸)
#   ③ 兩種混用     → 兩邊都在、且不重複
#   ④ 沒有 .base   → 退回純 status(舊呼叫端/手建 worktree 不因此變糟)
set -u
LIB="${CRON_LIB:-$HOME/Delvin-agent/scripts/lib_cron_runner.sh}"
PASS=0; FAIL=0
chk() { if [ "$2" = 1 ]; then echo "✅ $1"; PASS=$((PASS+1)); else echo "❌ $1"; FAIL=$((FAIL+1)); fi; }
[ -f "$LIB" ] || { echo "❌ 找不到 lib:$LIB"; exit 1; }

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
REPO="$TMP/repo"
mkdir -p "$REPO"
git -C "$REPO" init -q -b main
git -C "$REPO" config user.email t@t; git -C "$REPO" config user.name t
printf 'base\n' > "$REPO/a.py"; printf 'base\n' > "$REPO/b.py"
git -C "$REPO" add -A >/dev/null; git -C "$REPO" commit -qm base

# lib 用 CRON_LIB_REPO 定位主樹;只取這三支 helper,不跑 lib 的其他副作用
CRON_LIB_REPO="$REPO"
eval "$(awk '/^cron_fix_wt_create\(\)/,/^}/' "$LIB")"
eval "$(awk '/^cron_fix_wt_changes\(\)/,/^}/' "$LIB")"
eval "$(awk '/^cron_fix_wt_destroy\(\)/,/^}/' "$LIB")"
chk "S0 三支 helper 都抽得出來(抽不到=lib 已改而本測試沒跟上)" \
    "$(type -t cron_fix_wt_create >/dev/null 2>&1 && type -t cron_fix_wt_changes >/dev/null 2>&1 && type -t cron_fix_wt_destroy >/dev/null 2>&1 && echo 1 || echo 0)"

# ── ① 代理 commit ──
WT1="$TMP/wt1"
cron_fix_wt_create "$WT1" || { echo "❌ worktree 建立失敗"; exit 1; }
chk "①a create 有落下 .base 起跑點" "$([ -f "$WT1.base" ] && echo 1 || echo 0)"
printf 'fixed\n' > "$WT1/a.py"
printf 'new test\n' > "$WT1/scripts_new.py"
git -C "$WT1" add -A >/dev/null; git -C "$WT1" -c user.email=t@t -c user.name=t commit -qm "agent fix"
OUT1="$(cron_fix_wt_changes "$WT1")"
chk "①b 代理 commit 的既有檔改動看得到(a.py)" "$(echo "$OUT1" | grep -qx 'a.py' && echo 1 || echo 0)"
chk "①c 代理 commit 的新增檔看得到(scripts_new.py)" "$(echo "$OUT1" | grep -qx 'scripts_new.py' && echo 1 || echo 0)"
chk "①d 沒動過的檔不該出現(b.py)" "$(echo "$OUT1" | grep -qx 'b.py' && echo 0 || echo 1)"

# ── ② 代理沒 commit(舊行為不可回歸) ──
WT2="$TMP/wt2"
cron_fix_wt_create "$WT2"
printf 'dirty\n' > "$WT2/a.py"
printf 'untracked\n' > "$WT2/c.py"
OUT2="$(cron_fix_wt_changes "$WT2")"
chk "②a 未 commit 的修改仍看得到(a.py)" "$(echo "$OUT2" | grep -qx 'a.py' && echo 1 || echo 0)"
chk "②b untracked 新檔仍看得到(c.py)" "$(echo "$OUT2" | grep -qx 'c.py' && echo 1 || echo 0)"

# ── ③ 混用:一半 commit 一半沒 commit,且不重複 ──
WT3="$TMP/wt3"
cron_fix_wt_create "$WT3"
printf 'committed\n' > "$WT3/a.py"
git -C "$WT3" add -A >/dev/null; git -C "$WT3" -c user.email=t@t -c user.name=t commit -qm "half"
printf 'committed then dirty\n' > "$WT3/a.py"     # 同一檔:兩邊都會列到
printf 'dirty only\n' > "$WT3/b.py"
OUT3="$(cron_fix_wt_changes "$WT3")"
chk "③a commit + 之後又改的檔只出現一次(a.py 去重)" "$([ "$(echo "$OUT3" | grep -cx 'a.py')" = 1 ] && echo 1 || echo 0)"
chk "③b 只有未 commit 改動的檔也在(b.py)" "$(echo "$OUT3" | grep -qx 'b.py' && echo 1 || echo 0)"

# ── ④ 沒有 .base:退回純 status,不可因此崩掉或吐雜訊 ──
WT4="$TMP/wt4"
cron_fix_wt_create "$WT4"
rm -f "$WT4.base"
printf 'committed\n' > "$WT4/a.py"
git -C "$WT4" add -A >/dev/null; git -C "$WT4" -c user.email=t@t -c user.name=t commit -qm "no base"
printf 'dirty\n' > "$WT4/b.py"
OUT4="$(cron_fix_wt_changes "$WT4")"
chk "④a 無 .base 時仍回得了未 commit 改動(b.py)" "$(echo "$OUT4" | grep -qx 'b.py' && echo 1 || echo 0)"
chk "④b 無 .base 時不吐錯誤訊息進清單" "$(echo "$OUT4" | grep -qiE 'fatal|error' && echo 0 || echo 1)"

# ── destroy 要把 .base 一起收掉(否則 /tmp 會殘留起跑點檔) ──
cron_fix_wt_destroy "$WT1"
chk "⑤ destroy 一併清掉 .base" "$([ ! -f "$WT1.base" ] && echo 1 || echo 0)"
cron_fix_wt_destroy "$WT2"; cron_fix_wt_destroy "$WT3"; cron_fix_wt_destroy "$WT4"

echo
echo "$PASS/$((PASS+FAIL)) 通過"
[ "$FAIL" = 0 ] || exit 1
