#!/usr/bin/env bash
# 大腦 sync 回滾偵測(2026-07-30 建,Delvin 核可)。
# 抓的失誤:sync commit 把 memory/ 或 skills/ 底下既有檔案「回滾成更早的版本」
#   = 有人的編輯被舊副本蓋回(2026-07-29 a061477 吃掉 website-design-team 的 Delvin 親令整天)。
#
# 判準=**內容回頭**:該 commit 的 blob hash 與這個檔案更早某個版本完全相同。
#   ⚠️ 第一版寫成「sync commit 有刪行就告警」是錯的:sync 例行在傳播兩機的正常編輯(改記憶、
#      groom MEMORY.md、壓縮 dept hub 都會刪行),2 小時歷史就 60+ 命中=假陽性災難。
#      正常編輯永遠產生「新內容」,不會 byte-equal 某個舊版;回滾才會。
# 整檔刪除(D)刻意不抓——可能是合法墓碑刪除(brain_deliver_mac.sh 會傳播刪除)。
# 每個 commit 只告警一次:掃完即推進 state 指標(防警報疲勞)。
# 背景/復原手法:memory project_brain_sync_skill_content_revert
set -u
REPO="${BRAIN_REVERT_REPO:-$HOME/delvin-claude-brain}"
STATE_DIR="${BRAIN_REVERT_STATE_DIR:-$HOME/.marketdaily-fallback/state}"
STATE="$STATE_DIR/brain_revert_last_sha"
LEDGER="$STATE_DIR/brain_revert_ledger.tsv"
DEPTH="${BRAIN_REVERT_DEPTH:-60}"      # 每個檔案往回比幾個版本
mkdir -p "$STATE_DIR"

cd "$REPO" 2>/dev/null || { echo "❌ brain repo 不存在:$REPO"; exit 1; }
HEAD_SHA=$(git rev-parse HEAD 2>/dev/null) || { echo "❌ 讀不到 HEAD"; exit 1; }
LAST=$(cat "$STATE" 2>/dev/null || true)

if [ -z "${LAST:-}" ] || ! git cat-file -e "${LAST}^{commit}" 2>/dev/null; then
  echo "$HEAD_SHA" > "$STATE"; echo "ℹ️ 首次執行(或 state 失效),基準=$HEAD_SHA"; exit 0
fi
if ! git merge-base --is-ancestor "$LAST" "$HEAD_SHA" 2>/dev/null; then
  echo "$HEAD_SHA" > "$STATE"; echo "⚠️ 歷史被改寫($LAST 非 HEAD 祖先),基準重設=$HEAD_SHA"; exit 0
fi
[ "$LAST" = "$HEAD_SHA" ] && { echo "✅ 無新 commit(基準 ${LAST:0:9})"; exit 0; }

RANGE="${LAST}..${HEAD_SHA}"
REPORT=""; N=0; SCANNED=0; FILES=0; FLAP=0
while IFS=$'\t' read -r sha subj; do
  [ -n "${sha:-}" ] || continue
  case "$subj" in sync:*) ;; *) continue ;; esac
  SCANNED=$((SCANNED + 1))
  while IFS=$'\t' read -r st path; do
    [ -n "${path:-}" ] || continue
    [ "$st" = "M" ] || continue                   # 只看「檔還在卻被改」
    FILES=$((FILES + 1))
    new_blob=$(git rev-parse "${sha}:${path}" 2>/dev/null) || continue
    # 往回找:這個 blob 是否等於本檔更早某個版本(=內容回頭)
    match=""
    for old_rev in $(git rev-list --max-count="$DEPTH" "${sha}^" -- "$path" 2>/dev/null); do
      old_blob=$(git rev-parse "${old_rev}:${path}" 2>/dev/null) || continue
      if [ "$old_blob" = "$new_blob" ]; then match="$old_rev"; break; fi
    done
    [ -n "$match" ] || continue
    # 被回滾區間內有沒有「真實工作 commit」(非 sync)。沒有=兩機來回鏡像的內容彈跳,
    # 不是資料損失,不告警(否則同樣是假陽性災難:實測 208 件裡絕大多數屬此類)。
    undone=$(git log --format='%h %s' "${match}..${sha}^" -- "$path" 2>/dev/null \
             | grep -v ' sync: ' | grep -v '^[0-9a-f]* sync:' | head -3 | tr '\n' '|')
    if [ -z "$undone" ]; then FLAP=$((FLAP + 1)); continue; fi
    REPORT="${REPORT}
  ${sha:0:9} 「${subj}」
    → ${path} 被回滾成 ${match:0:9} 的版本
    → 被抹掉的工作:${undone}"
    N=$((N + 1))
  done < <(git diff-tree --no-commit-id --name-status -r "$sha" -- memory skills)
done < <(git log --reverse --format='%H%x09%s' "$RANGE")

echo "$HEAD_SHA" > "$STATE"

if [ "$N" -gt 0 ]; then
  printf '%s\t%s\t%s\n' "$(TZ=Asia/Taipei date '+%F %T')" "$N" "$(printf '%s' "$REPORT" | tr '\n' ' ')" >> "$LEDGER"
  echo "❌ sync commit 把既有 memory/skills 檔案回滾成舊版(${N} 件)=有人的編輯被蓋掉(另有兩機鏡像彈跳 ${FLAP} 件不計):${REPORT}"
  echo ""
  echo "復原:git -C $REPO show <被抹掉的commit>:<path> → 同時寫回 live 與 repo,當下 commit+push"
  echo "     (只改 live 沒用,5 分鐘後 sync restore 會再蓋回)"
  echo "背景:memory project_brain_sync_skill_content_revert"
  exit 1
fi
echo "✅ $RANGE:${SCANNED} 個 sync commit / ${FILES} 個檔案變更,無真實工作被回滾(兩機鏡像彈跳 ${FLAP} 件,不計)"
