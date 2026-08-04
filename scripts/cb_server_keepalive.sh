#!/bin/bash
# cb_analyzer 伺服器守護:8911 沒人聽就拉起來(重開機自動復活;掛掉 5 分內自癒)
#
# 2026-08-05 補守衛(20 積木稽核抓到本支裸奔):
#  · 積木15 冪等 —— pkill + nohup 這段序列必須單例。兩輪重疊時雙方都 pkill 再各起一隻,
#    結果是兩個 cb_server 搶 8911(或互相殺),自癒器自己變成故障源。
#  · 積木13 告警 —— 原本自癒完全靜默。單次自癒本來就該安靜(那是它的工作),
#    但**反覆自癒**是病徵沒人看得到;拉不起來更是硬故障卻只寫進 log。
#    故:24h 內 ≥3 次自癒 → 告警(每日至多一則);拉起失敗 → 告警(1 小時冷卻,防 */5 洗版)。
set -u
exec 9>/tmp/cb_server_keepalive.lock
flock -n 9 || exit 0

DIR=/home/userdelvin/Delvin-agent/cb_analyzer
LOG=$DIR/server.log
STATE=$HOME/.marketdaily-fallback/state
LEDGER=$STATE/cb_server_restarts          # 每次自癒一行 epoch
COOL_FLAP=$STATE/cb_server_flap_alerted   # 反覆自癒告警冷卻
COOL_DEAD=$STATE/cb_server_dead_alerted   # 硬故障告警冷卻
mkdir -p "$STATE"

notify() {
  "$HOME/Delvin-agent/.venv/bin/python" \
    "$HOME/.marketdaily-fallback/notify_admin.py" "$1" >/dev/null 2>&1
}
# 冷卻檔比 N 秒新就跳過;否則蓋戳記並放行
cooled() {
  local f="$1" secs="$2" now last
  now=$(date +%s); last=$(cat "$f" 2>/dev/null || echo 0)
  [ $((now - last)) -lt "$secs" ] && return 1
  echo "$now" > "$f"; return 0
}

# 完成心跳:本支輸出全進 /dev/null,它自己死掉(被移出 crontab/崩潰)沒人看得到。
# 戳記交給 fleet_liveness 的產出級心跳監看(不另建 cron)。
beat() { date '+%F %T' > "$STATE/cb_server_keepalive.beat"; }

curl -s -m 5 -o /dev/null http://localhost:8911/ && { beat; exit 0; }

pkill -f "python3 cb_server.py$" 2>/dev/null
sleep 1
cd "$DIR" || exit 1
nohup python3 cb_server.py >> "$LOG" 2>&1 &
sleep 3

if curl -s -m 5 -o /dev/null http://localhost:8911/; then
  beat
  echo "$(date '+%F %T') cb_server 已重新拉起" >> "$LOG"
  rm -f "$COOL_DEAD"                       # 活過來就解除硬故障冷卻,之後再死能立刻喊
  NOW=$(date +%s); echo "$NOW" >> "$LEDGER"
  # 只留 24h 內的紀錄,順便當計數
  CUT=$((NOW - 86400))
  awk -v c="$CUT" '$1 >= c' "$LEDGER" > "$LEDGER.tmp" && mv "$LEDGER.tmp" "$LEDGER"
  N=$(wc -l < "$LEDGER")
  if [ "$N" -ge 3 ] && cooled "$COOL_FLAP" 86400; then
    notify "⚠️ cb_server 反覆自癒:24 小時內第 ${N} 次被 keepalive 拉起(8911)。自癒有效但它一直在死,請查 $LOG 的崩潰原因。"
  fi
else
  echo "$(date '+%F %T') cb_server 拉起失敗" >> "$LOG"
  cooled "$COOL_DEAD" 3600 && \
    notify "🔴 cb_server 拉不起來:keepalive 重啟後 8911 仍無回應(cb-desk / CB 分析站會是掛的)。查 $LOG。"
fi
