#!/bin/bash
# MarketDaily IG 留言閘門漏斗 runner(2026-07-11 上線,源自 @100xengineers 拆解)。
# crontab 每 10 分鐘跑一次 comment_funnel.py:掃自家閘門貼文留言「早鳥」→自動回訂閱連結。
# 冪等(state 防重),近 14 天無閘門貼文=秒退無動作;git pull 不在此做(社群 runner 已管)。
#
# 2026-08-05 補守衛(20 積木稽核抓到本支裸奔):
#  · 積木15 冪等 —— py 內部有 state 防重,但那是**單行程內**的防重;兩輪重疊時
#    雙方都可能在對方寫 state 前讀到同一則未回覆留言 → **對真實用戶的 IG 留言雙回覆**。
#    這是對外可見的損害,不是內部帳目,故加單例鎖。
#  · 積木13 告警 —— 這支會替我們對外發言,原本失敗只進 log 沒人看;漏斗死掉可以無聲無息。
#    改走 cron_run_and_alert(指紋去重),順帶讓它的 log 進 <job>_<date>.log 格式,
#    被 fleet_liveness 艦隊心跳納管(原本連納管都沒有)。
set -u
export HOME="${HOME:-/home/userdelvin}"
export PATH="$HOME/Delvin-agent/.venv/bin:$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"
REPO="$HOME/Delvin-agent"
PY="$REPO/.venv/bin/python"
[ -x "$PY" ] || PY=python3

exec 9>/tmp/comment_funnel.lock
flock -n 9 || exit 0

source "$REPO/scripts/lib_cron_runner.sh"
cd "$REPO/marketing" || exit 1
cron_run_and_alert "comment_funnel" -- "$PY" comment_funnel.py
