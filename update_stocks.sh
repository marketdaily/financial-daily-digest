#!/bin/zsh
# update_stocks.sh — 每月自動更新股票資料庫並部署
# 2026-06-06 重寫:加 PATH(launchd 環境找不到 npx/node)、移除致命 set -e、分段容錯

# launchd 環境 PATH 極簡,明確補上 node/npx/python 路徑
export PATH="/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

PROJECT_DIR="/Users/delvin/Downloads/Delvin agent"
LOG="$PROJECT_DIR/update_stocks.log"

cd "$PROJECT_DIR" || { echo "[$(date '+%Y-%m-%d %H:%M')] FATAL: cd 失敗" >> "$LOG"; exit 1; }

echo "[$(date '+%Y-%m-%d %H:%M')] ===== 開始更新股票資料庫 =====" >> "$LOG"

# 第一段:抓股票資料(失敗不中止,記錄後繼續)
if python3 fetch_stocks.py >> "$LOG" 2>&1; then
    echo "[$(date '+%Y-%m-%d %H:%M')] ✅ fetch_stocks.py 完成" >> "$LOG"
else
    echo "[$(date '+%Y-%m-%d %H:%M')] ❌ fetch_stocks.py 失敗 (rc=$?),仍嘗試部署現有資料" >> "$LOG"
fi

# 第二段:部署(失敗只記錄,不讓整支變 127)
if npx wrangler pages deploy docs --project-name marketdaily --commit-dirty=true >> "$LOG" 2>&1; then
    echo "[$(date '+%Y-%m-%d %H:%M')] ✅ wrangler 部署完成" >> "$LOG"
else
    echo "[$(date '+%Y-%m-%d %H:%M')] ❌ wrangler 部署失敗 (rc=$?)" >> "$LOG"
fi

echo "[$(date '+%Y-%m-%d %H:%M')] ===== 結束 =====" >> "$LOG"
