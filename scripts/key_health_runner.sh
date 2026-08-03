#!/bin/bash
# key 健康巡檢 runner(API/MCP 伺服器部首員,2026-08-03 部門成立日上線)。
# 每天 TW 10:45 摸一輪數據/服務類 API key(LLM 廠商歸 free_capacity_radar,不重複)。
# 全綠靜默;任何 key 死/額度異常 → cron_run_and_alert 推 admin(指紋去重)。週日自帶擴檢。
set -u
export HOME="${HOME:-/home/userdelvin}"
export PATH="$HOME/Delvin-agent/.venv/bin:$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"
REPO="$HOME/Delvin-agent"; PY="$REPO/.venv/bin/python"
cd "$REPO" || exit 1
source "$REPO/scripts/lib_cron_runner.sh"

cron_time_gate "10:45" "11:14"
cron_daily_lock "key_health"

BASE="$HOME/.marketdaily-fallback"; mkdir -p "$BASE/logs"
exec >> "$BASE/logs/key_health_$(TZ=Asia/Taipei date +%Y-%m-%d).log" 2>&1
echo "=== $(date '+%F %T %z') key health patrol start ==="
cron_run_and_alert "key_health" -- "$PY" scripts/key_health_patrol.py --quiet
# 艦隊 liveness 總表(同窗口一天一輪):106+ cron+intel 連接器的靜默死亡偵測,自校準間隔
cron_run_and_alert "fleet_liveness" -- "$PY" scripts/fleet_liveness.py --quiet
echo "=== $(date '+%F %T %z') done ==="
