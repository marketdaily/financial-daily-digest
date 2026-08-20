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
# rc=1 的語意是「查到有 job 靜默」不是「我掛了」——沒這行的話 fleet_liveness 每次
# 盡責報告就讓自己的戳記凍住,下一輪把自己列進靜默名單(2026-08-20 實際發生)。
CRON_OK_ON_RC=1 cron_run_and_alert "fleet_liveness" -- "$PY" scripts/fleet_liveness.py --quiet
# 這兩支每天整檔重寫自己的 state,但 2026-08-10 前沒有 persist owner → 檔案永遠髒著:
#   ① dirty_tree_watch 每天告警「tracked 檔持續髒逾 120h」
#   ② stale_base_lint 把「工作樹比 HEAD 新很多」誤判成「拿過期底稿整檔覆寫」而恆紅
#   ③ cron_abort_if_dirty 的守門 runner 會因為這兩個檔而略過
# 寫者收自己的輸出(慣例見 valuation_ledger_runner)。
cron_git_persist "chore(state): key/艦隊健康巡檢狀態每日更新 (winrig) [skip ci]" \
  state/key_health.json state/fleet_liveness.json
echo "=== $(date '+%F %T %z') done ==="
