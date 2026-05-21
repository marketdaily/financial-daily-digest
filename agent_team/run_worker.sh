#!/bin/bash
# 本機夜間 Worker — 每 30 分鐘由 launchd 觸發
REPO="/Users/delvin/Downloads/Delvin agent"
CLAUDE="$(command -v claude 2>/dev/null || echo /Applications/cmux.app/Contents/Resources/bin/claude)"
cd "$REPO" || exit 1
mkdir -p agent_team/logs
LOG="agent_team/logs/worker-$(date +%Y%m%d).log"
LOCK="agent_team/.worker.lock"

# 清除殘留鎖:行程被強制中止(kill -9 / 當機)時 trap 不觸發,鎖會永久卡住
if [ -d "$LOCK" ] && [ -n "$(find "$LOCK" -maxdepth 0 -mmin +50 2>/dev/null)" ]; then
  echo "$(date '+%F %T') 清除殘留鎖(>50 分鐘)" >> "$LOG"
  rmdir "$LOCK" 2>/dev/null
fi

if ! mkdir "$LOCK" 2>/dev/null; then
  echo "$(date '+%F %T') 已有 worker 執行中,跳過" >> "$LOG"
  exit 0
fi
trap 'rmdir "$LOCK" 2>/dev/null' EXIT

# 清掉 14 天前的舊日誌
find agent_team/logs -name 'worker-*.log' -mtime +14 -delete 2>/dev/null

{
  echo "=== $(date '+%F %T') worker start ==="
  /usr/bin/caffeinate -i "$CLAUDE" -p "你是 MarketDaily Agent Team 的夜間 Worker。請讀取並嚴格依照 agent_team/worker.md 的指令,執行一次值班。" --dangerously-skip-permissions
  echo "=== $(date '+%F %T') worker end ==="
} >> "$LOG" 2>&1
