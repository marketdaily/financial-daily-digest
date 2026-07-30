#!/usr/bin/env bash
# update_stocks.sh — 每月自動更新股票資料庫並部署
# 2026-06-06 重寫:加 PATH(launchd 環境找不到 npx/node)、移除致命 set -e、分段容錯

# launchd 環境 PATH 極簡,明確補上 node/npx/python 路徑
export PATH="/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

# 專案路徑機器自判(2026-07-30 A 級改制:本工作已從 Mac launchd 搬到 winrig cron)。
# 沿用 sync.sh 的同一套判斷,不寫死任何一台的路徑。
if [ -d "$HOME/Delvin-agent" ]; then
  PROJECT_DIR="$HOME/Delvin-agent"                       # winrig(WSL)
else
  PROJECT_DIR="/Users/delvin/Downloads/Delvin agent"     # Mac
fi
LOG="$PROJECT_DIR/update_stocks.log"

cd "$PROJECT_DIR" || { echo "[$(date '+%Y-%m-%d %H:%M')] FATAL: cd 失敗" >> "$LOG"; exit 1; }

RC=0   # 分段容錯照舊,但要記住有沒有出事:原本整支永遠 exit 0,掛了 cron 也不會告警。
echo "[$(date '+%Y-%m-%d %H:%M')] ===== 開始更新股票資料庫 =====" >> "$LOG"

# 第一段:抓股票資料(失敗不中止,記錄後繼續)
if python3 fetch_stocks.py >> "$LOG" 2>&1; then
    echo "[$(date '+%Y-%m-%d %H:%M')] ✅ fetch_stocks.py 完成" >> "$LOG"
else
    echo "[$(date '+%Y-%m-%d %H:%M')] ❌ fetch_stocks.py 失敗 (rc=$?),仍嘗試部署現有資料" >> "$LOG"
    RC=1
fi

# 第二段:部署(失敗只記錄,不讓整支變 127)
if npx wrangler pages deploy docs --project-name marketdaily --commit-dirty=true >> "$LOG" 2>&1; then
    echo "[$(date '+%Y-%m-%d %H:%M')] ✅ wrangler 部署完成" >> "$LOG"
else
    echo "[$(date '+%Y-%m-%d %H:%M')] ❌ wrangler 部署失敗 (rc=$?)" >> "$LOG"
    RC=1
fi

# 產出進版控:否則 docs/stocks.js 每月留一份未提交變更,會絆倒其他 cron 的 dirty 守門閘。
if [ -f "$HOME/Delvin-agent/scripts/lib_cron_runner.sh" ]; then
  . "$HOME/Delvin-agent/scripts/lib_cron_runner.sh"
  cron_git_persist "chore(stocks): 每月股票宇宙更新" docs/stocks.js || true
fi
echo "[$(date '+%Y-%m-%d %H:%M')] ===== 結束 (rc=$RC) =====" >> "$LOG"
exit $RC
