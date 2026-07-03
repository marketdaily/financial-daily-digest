#!/bin/bash
# 通用 winrig cron 常駐/自癒 pattern 標準模板庫。
# 抽自 ~/.marketdaily-fallback/social_post_runner.sh 的手工實作,把「時間窗口門/每日鎖(防雙源重跑)/
# 失敗自動 LINE 告警/best-effort git 持久化」四件事變成可 source 的函式,未來新排程任務直接組裝。
#
# 用法(source 這個檔案,見 scripts/cron_template.sh 完整範例):
#   source "$HOME/Delvin-agent/scripts/lib_cron_runner.sh"
#   cron_time_gate "14:00" "14:09"           # 不在窗口內就靜默 exit 0(跨夜窗口如 "23:50" "00:10" 也支援)
#   cron_daily_lock "social"                 # 今天已跑過(mkdir 鎖存在)就靜默 exit 0,否則佔鎖繼續
#   cron_run_and_alert "digest_send" -- python3 foo.py   # 執行指令,log 進 logs/<name>_<日期>.log;
#                                                          # 非 0 結束碼→自動呼叫 notify_admin.py 推 admin(含 log tail)
#   cron_git_persist "chore: xxx [skip ci]" path/to/file  # best-effort commit+pull --rebase+push,不阻斷主流程
#
# 依賴:~/.marketdaily-fallback/notify_admin.py(web push+桌面 toast 雙通道,自行從 .env 讀
# MARKETDAILY_ALERT_TOKEN,已修 Cloudflare WAF User-Agent 403 問題;2026-07-04 前誤用舊版
# scripts/notify_line.py,因呼叫端從未 export token 到 os.environ 而靜默跳過,失敗告警形同虛設)。
set -u
CRON_LIB_REPO="${CRON_LIB_REPO:-$HOME/Delvin-agent}"

_hhmm_to_min() {
  local h=${1%%:*} m=${1##*:}
  h=$((10#$h)); m=$((10#$m))
  echo $((h * 60 + m))
}

# cron_time_gate START END  (HH:MM,台灣時間)。不在窗口內 → exit 0。
cron_time_gate() {
  local start_min end_min now_min
  start_min=$(_hhmm_to_min "$1")
  end_min=$(_hhmm_to_min "$2")
  now_min=$(_hhmm_to_min "$(TZ=Asia/Taipei date +%H:%M)")
  if [ "$start_min" -le "$end_min" ]; then
    { [ "$now_min" -ge "$start_min" ] && [ "$now_min" -le "$end_min" ]; } || exit 0
  else
    { [ "$now_min" -ge "$start_min" ] || [ "$now_min" -le "$end_min" ]; } || exit 0
  fi
}

# cron_daily_lock NAME  防同一天重跑/防雙 cron source 撞期。用 mkdir 原子鎖,今天已存在就 exit 0。
cron_daily_lock() {
  local name="$1"
  local date_tag lock_dir
  date_tag=$(TZ=Asia/Taipei date +%Y-%m-%d)
  lock_dir="$CRON_LIB_REPO/logs/locks"
  mkdir -p "$lock_dir"
  mkdir "$lock_dir/${name}.${date_tag}" 2>/dev/null || exit 0
}

# cron_run_and_alert NAME [--] CMD...   跑指令,log 到 logs/<name>_<日期>.log;失敗自動告警 admin。
# 告警走 notify_admin.py(web push + winrig 桌面 toast 雙通道,自行從 .env 讀 token、已修
# Cloudflare WAF User-Agent 403 問題)——舊版呼叫 notify_line.py 只認 os.environ 裡的
# MARKETDAILY_ALERT_TOKEN(呼叫端從未 export 過)會靜默跳過,失敗告警形同虛設,2026-07-04 修正。
cron_run_and_alert() {
  local name="$1"; shift
  [ "${1:-}" = "--" ] && shift
  local date_tag log_dir log rc tail_msg
  date_tag=$(TZ=Asia/Taipei date +%Y-%m-%d)
  log_dir="$CRON_LIB_REPO/logs"
  mkdir -p "$log_dir"
  log="$log_dir/${name}_${date_tag}.log"
  echo "=== $(date '+%F %T %z') cron_run_and_alert:${name} start ===" >> "$log"
  "$@" >> "$log" 2>&1
  rc=$?
  echo "=== end rc=${rc} ===" >> "$log"
  if [ "$rc" -ne 0 ]; then
    tail_msg=$(tail -c 800 "$log")
    MD_REPO="$CRON_LIB_REPO" "$CRON_LIB_REPO/.venv/bin/python" "$HOME/.marketdaily-fallback/notify_admin.py" \
      "🔴 winrig cron『${name}』失敗 rc=${rc} $(TZ=Asia/Taipei date '+%F %T')
--- log tail ---
${tail_msg}" >/dev/null 2>&1
  fi
  return "$rc"
}

# cron_git_persist "commit message" file1 [file2 ...]  best-effort 持久化,絕不因失敗中斷主流程。
# 安全鐵則:絕不 --autostash(會把別視窗未 commit 的工作偷塞進 stash 再賭它 pop 得回來)。
# 只在「我們自己這批 commit 完之後,tracked 檔案已完全乾淨」時才 pull --rebase;
# 只要還殘留任何別人的未 commit 修改(M/A/D/R,不含 untracked ??),就跳過 pull 只試 push——
# push 若因落後遠端被拒會安靜失敗,commit 留在本機等下次乾淨時再補推,絕不去動別人的檔案。
cron_git_persist() {
  local msg="$1"; shift
  ( cd "$CRON_LIB_REPO" || exit 0
    git add "$@" 2>/dev/null
    git diff --staged --quiet 2>/dev/null && exit 0
    git -c user.name=winrig -c user.email=winrig@marketdaily commit -m "$msg" 2>/dev/null
    if ! git status --porcelain 2>/dev/null | grep -qv '^??'; then
      git pull --rebase origin main 2>/dev/null
    fi
    git push origin HEAD:main 2>/dev/null
  ) || true
}

# cron_safe_pull  取代裸 `git pull --autostash origin main`。只在 tracked 檔案完全乾淨
# (不含 untracked ??)時才 pull --rebase；有殘留別人的未 commit 修改就靜默跳過，絕不 autostash。
# 用在「開工前先同步最新」的場景（commit 不是重點，只是想拿到 origin 最新）。
cron_safe_pull() {
  ( cd "$CRON_LIB_REPO" || exit 0
    if ! git status --porcelain 2>/dev/null | grep -qv '^??'; then
      git pull --rebase origin main 2>/dev/null
    fi
  ) || true
}

# cron_abort_if_dirty  若 repo 已有 tracked 未 commit 修改（不含 untracked ??），
# 直接讓呼叫腳本 exit 0（靜默略過整輪）。給任何後面會做 `git checkout -- .` /
# `git reset --hard` 這類整樹操作的腳本在動手前守門用 — 保證流程走到那一步時，
# 樹在腳本自己開始改動之前就是乾淨的，後續的 revert 只會碰到腳本自己造成的變動，
# 不會誤傷別人的 WIP。呼叫點必須在任何 git 操作之前。
cron_abort_if_dirty() {
  if ( cd "$CRON_LIB_REPO" && git status --porcelain 2>/dev/null | grep -qv '^??' ); then
    echo "[cron_abort_if_dirty] repo 有未 commit 修改(可能是別視窗 WIP)，本輪略過保護"
    exit 0
  fi
}
