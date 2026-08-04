#!/usr/bin/env bash
# winrig→Mac 大腦同步(繞過 Mac 死掉的 GitHub 認證,走 Tailscale SSH)。
# Mac 一上線就把 statusline + 自主機器大腦 + 新記憶推過去。cron */15。
# 為何不用 git:Mac 的 delvin-claude-brain 無 GitHub 認證,pull/push 皆 fatal。
set -uo pipefail

# 單例鎖(2026-08-05):本支 */5 但要跑 1.7GB rsync + 三趟 SSH tar,超過 5 分鐘完全可能。
# 重疊的後果不是慢,是**壞資料**:Mac 端的 /tmp/mem.tgz 與 /tmp/memory 是固定路徑,
# 兩輪並行時 B 會覆蓋 A 正在解壓的包 → A 把截斷的記憶包 rsync 進真目錄。
exec 9>/tmp/brain_deliver_mac.lock
flock -n 9 || exit 0

MAC="delvin@100.78.136.77"
SSH="ssh -o BatchMode=yes -o ConnectTimeout=8 $MAC"

# 完成心跳(2026-08-05):本支不寫任何心跳,brain_sync_deadman 看的是 sync.sh 的 .sync-health,
# **管不到這條 SSH 路徑** → 它靜默死掉可以沒人知道。戳記由 fleet_liveness 的產出級心跳監看。
BEAT="$HOME/.marketdaily-fallback/state/brain_deliver_mac.beat"
mkdir -p "$(dirname "$BEAT")"
beat() { date '+%F %T' > "$BEAT"; }

$SSH 'true' 2>/dev/null || { beat; exit 0; }   # Mac 離線就靜默跳過(本支仍算活著)

# 1) statusline(winrig 為權威版):只在內容不同才送
LOCAL_MD=$(md5sum ~/.claude/statusline-command.sh 2>/dev/null | cut -d' ' -f1)
REMOTE_MD=$($SSH 'md5 -q ~/.claude/statusline-command.sh 2>/dev/null || md5sum ~/.claude/statusline-command.sh 2>/dev/null | cut -d" " -f1' 2>/dev/null)
if [ "$LOCAL_MD" != "$REMOTE_MD" ]; then
  cat ~/.claude/statusline-command.sh | $SSH 'cat > ~/.claude/statusline-command.sh.tmp && mv ~/.claude/statusline-command.sh.tmp ~/.claude/statusline-command.sh && chmod +x ~/.claude/statusline-command.sh'
  echo "$(date) statusline → Mac"
fi

# 2) 自主機器大腦(排除 state runtime)
# 2026-07-30:整包 tar 換 rsync 增量。原本每輪把 ~/autonomous(1.7GB,eval/runs 816M +
# ssf_basis 604M)完整壓縮過 SSH 再解開,單它就讓這支跑成重活,也是 deliver 沒法提頻的原因。
# rsync 同樣語義(含刪除)但只傳差異,無變更時幾乎零流量。
# ⚠️ -e 只能給 ssh 指令本身,不能含主機:本檔的 $SSH 已內含 $MAC,傳給 -e 會讓主機重複、
# rsync 靜默失敗(2026-07-30 當場踩到,還誤以為「變快了」)。故這裡自己拼不含主機的版本。
rsync -a --delete --exclude='state' --exclude='research/__pycache__' \
  -e "ssh -o BatchMode=yes -o ConnectTimeout=8" "$HOME/autonomous/" "$MAC:autonomous/" 2>/dev/null

# 3) 記憶 union(winrig 新學的流到 Mac,不覆蓋 Mac 較新檔)
#    2026-07-30:cp -Rn → rsync -au。-n 是 no-clobber,既有檔一律不碰 → winrig 對
#    既有記憶檔的「編輯」永遠送不到 Mac(只有新增檔送得到)。-u=來源較新才覆蓋,
#    同樣保護 Mac 較新的編輯,且更新傳得過去。同 sync.sh 的同批修正。
tar czf - -C "$HOME/.claude/projects/-home-userdelvin-Delvin-agent" memory 2>/dev/null \
  | $SSH 'cat > /tmp/mem.tgz && rm -rf /tmp/memory && tar xzf /tmp/mem.tgz -C /tmp/ 2>/dev/null && \
          D="/Users/delvin/.claude/projects/-Users-delvin-Downloads-Delvin-agent/memory" && mkdir -p "$D" && rsync -au /tmp/memory/ "$D/" 2>/dev/null'

# 3.2) 墓碑執行(2026-07-30 A 級改制補洞):刪除的傳播原本靠 Mac 自己跑 sync.sh 的
#      墓碑段;Mac 停跑 sync 後刪除再也到不了 Mac,殭屍檔問題會原地復活(實測 514 vs 513)。
#      改由 deliver 代勞:.tombstones 已隨步驟3 送達 Mac,在 Mac 端照清單 rm 即可。
#      不用 rsync --delete 做鏡像——那會在 collect 收走之前先殺掉 Mac 剛產的新檔。
$SSH 'D="/Users/delvin/.claude/projects/-Users-delvin-Downloads-Delvin-agent/memory"; if [ -f "$D/.tombstones" ]; then while read -r _d n; do [ -n "$n" ] && rm -f "$D/$n"; done < "$D/.tombstones"; fi' 2>/dev/null

# 3.5) 自訂 skills(2026-07-11 補缺口:Mac git 認證死後從未收過新 skill)。
#      rsync -au 增量+只補新不覆蓋 Mac 較新檔(同 sync.sh union 慣例);含 CATALOG/GOVERNANCE。
rsync -au --exclude='.git' -e "ssh -o BatchMode=yes -o ConnectTimeout=8" \
  "$HOME/.claude/plugins/marketplaces/delvin-custom/" \
  "$MAC:.claude/plugins/marketplaces/delvin-custom/" 2>/dev/null \
  && echo "$(date) skills → Mac"

# 4) Obsidian vault(2026-07-08):導覽頁+.obsidian+記憶鏡像直送 Mac 的 repo 資料夾。
#    git 對 Mac 已死,vault 頁面只有這條路;Mac 端用 Obsidian 直開 ~/delvin-claude-brain
#    (原生路徑,無 Windows 的 9P/EISDIR 問題)。repo/autonomous 由 Mac 自己的 launchd
#    sync.sh 每日 13:00 從 ~/autonomous 重建=靠步驟 2 保鮮,這裡不重複送。
( cd "$HOME/delvin-claude-brain" && tar czf - HOME.md GRAPH-HEALTH.md MOC-*.md .obsidian memory 2>/dev/null ) \
  | $SSH 'mkdir -p ~/delvin-claude-brain && cat > /tmp/vault.tgz && tar xzf /tmp/vault.tgz -C ~/delvin-claude-brain 2>/dev/null'
beat
exit 0
