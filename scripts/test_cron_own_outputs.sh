#!/usr/bin/env bash
# cron 入口守門的「自家產物豁免」迴歸測試(2026-09-07 根治自鎖後補)。
#
# 守的災難(不是措辭):agent_board 是唯一會 commit docs/data/board.json 的 runner,
# 而它的 scope 是 docs ⇒ 那個檔一旦留成髒的,它會被自己的產物擋住;它一天只跑 14:40
# 一次沒有重試 ⇒ 整條 docs cron 生態鏈餓死 24h 起跳(09-01 兩天;09-07 再犯,當天早班
# digest_archive_seo 全讓路,早報存檔頁一整天沒有訂閱 CTA)。
#
# 三個情境必須同時成立,少一個豁免就是「放行別人的 WIP」而不是「解自鎖」:
#   A 只有自家產物髒 + 有豁免 → 續行
#   B 同樣狀態但沒宣告豁免    → 讓路(對照組;沒有它,「永遠續行」也會讓 A 綠)
#   C 自家產物 + 別人的檔都髒 → 仍讓路(豁免只放自己那一個檔)
set -u
LIB="$(cd "$(dirname "$0")" && pwd)/lib_cron_runner.sh"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
PASS=0; FAIL=0
chk() { if [ "$2" = "$3" ]; then PASS=$((PASS+1)); else FAIL=$((FAIL+1)); echo "  ✗ $1: 期望 $3 得到 $2"; fi; }

git init -q "$TMP"
mkdir -p "$TMP/docs/data"
echo '{"a":1}' > "$TMP/docs/data/board.json"
echo 'x' > "$TMP/docs/other.html"
git -C "$TMP" add -A
git -C "$TMP" -c user.email=t@t -c user.name=t commit -qm init

# 守門讓路的方式是 exit 0,所以每個情境都跑在子行程裡,用「有沒有印出續行標記」判定
probe() {  # $1=own 宣告(可空)  → 印 CONTINUED 或空
  ( cd "$TMP" || exit 1
    export CRON_LIB_REPO="$TMP" CRON_STARVE_STATE_DIR="$TMP/state" CRON_NOTIFY_CMD=true
    # shellcheck disable=SC1090
    source "$LIB"
    CRON_OWN_OUTPUTS="$1" cron_abort_if_dirty_scoped agent_board docs
    echo CONTINUED ) 2>/dev/null | grep -c CONTINUED
}

echo '{"a":2}' > "$TMP/docs/data/board.json"          # 只有自家產物髒
chk "A 自家產物髒+豁免 → 續行"   "$(probe 'docs/data/board.json')" 1
chk "B 同狀態無豁免 → 讓路"      "$(probe '')"                     0

echo 'zz' > "$TMP/docs/other.html"                     # 別人的檔也髒
chk "C 別人的檔也髒 → 仍讓路"    "$(probe 'docs/data/board.json')" 0

# D:豁免清單不可用前綴亂吃(宣告 board.json 不該連 board.json.bak 一起放行)
git -C "$TMP" checkout -q -- docs/other.html
echo 'bak' > "$TMP/docs/data/board.json.bak"
git -C "$TMP" add -A
git -C "$TMP" -c user.email=t@t -c user.name=t commit -qm bak
echo 'bak2' > "$TMP/docs/data/board.json.bak"
chk "D 只精確比對檔名,不吃前綴" "$(probe 'docs/data/board.json')" 0

echo "── cron 自家產物豁免: ${PASS}✓ ${FAIL}✗"
[ "$FAIL" = 0 ]
