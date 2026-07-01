#!/bin/bash
# 範例:如何用 lib_cron_runner.sh 三分鐘生出一支「排程+防重跑+失敗自癒告警+持久化」的 winrig cron 腳本。
# 複製這份改掉 NAME/WINDOW/實際工作指令即可,不必重寫 lock/告警邏輯。
#
# 部署:crontab -e 加一行(例如每 10 分鐘喚醒,腳本自己用 time_gate 決定要不要真的跑):
#   */10 * * * * /home/userdelvin/Delvin-agent/scripts/cron_template.sh >> /home/userdelvin/Delvin-agent/logs/cron_template_wake.log 2>&1
set -u
export HOME="${HOME:-/home/userdelvin}"
REPO="$HOME/Delvin-agent"
source "$REPO/scripts/lib_cron_runner.sh"

cron_time_gate "14:00" "14:09"      # 只在此台灣時間窗口內繼續往下跑,否則靜默 exit 0
cron_daily_lock "example_job"        # 今天已跑過就 exit 0,防雙 cron source 撞期

cron_run_and_alert "example_job" -- echo "這裡放實際工作指令,例如: python3 my_script.py"

cron_git_persist "chore: example_job persist [skip ci]" logs/example_job_*.log
