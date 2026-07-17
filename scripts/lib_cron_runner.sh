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
# 2026-07-07 修正①:commit 一定要帶 pathspec(`-- "${paths[@]}"`)限定只收這批路徑——
# 先前 `git add "$@"` 之後裸 `git commit`(無 pathspec)會把 index 裡「當下任何已 staged
# 但不是這次呼叫加的東西」一起吃進來(例如另一個 session 手動 git add 完還沒 commit
# 就被搶先的 cron 撈走,冠上不相干的 commit message)。pathspec-limited commit 已用
# 隔離 temp repo 驗證:只會納入指定路徑,其他已 staged 內容原封不動留在 index。
# 2026-07-07 修正②(獨立驗證子代理抓到):`git add`/`git commit --` 對多重 pathspec
# 是全有全無的——只要其中一個路徑「目前不存在也未被 git 追蹤過」(例如某個目錄要等
# promote 腳本第一次真的產生檔案才會出現,呼叫端提前把這個路徑寫進呼叫參數),整條
# git add/commit 會直接失敗,連同一批裡其他真的有異動的路徑也完全不會被 commit——
# `marketing_agents_weekly.sh` 傳的 `marketing/assets/posts/ad_creative` 在沒有新
# 核准草稿的 retry tick 就是這種情境,已用隔離 repo 重現(approved 狀態寫入被無聲吃掉,
# 沒有任何錯誤訊息)。修法:git add/commit 前先把 "$@" 過濾成「當下真的存在」的路徑
# (`[ -e ]`,對本專案這批純新增/累積型 ledger 檔案已足夠——沒有 caller 需要靠這個函式
# 提交刻意刪除 tracked 檔案),不存在的路徑直接跳過,不拖累同批次其他有效路徑。
cron_git_persist() {
  local msg="$1"; shift
  ( cd "$CRON_LIB_REPO" || exit 0
    local paths=() p
    for p in "$@"; do
      [ -e "$p" ] && paths+=("$p")
    done
    [ "${#paths[@]}" -eq 0 ] && exit 0
    git add "${paths[@]}" 2>/dev/null
    git -c user.name=winrig -c user.email=winrig@marketdaily commit -m "$msg" -- "${paths[@]}" >/dev/null 2>&1 || exit 0
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

# cron_consume_force_marker MARKER_PATH  event-driven 提前觸發用:marker 檔案存在就刪除
# 並 return 0(呼叫端應略過平常的星期/時間閘門,直接繼續);不存在 return 1(維持原本閘門)。
# 用途:某個「只在特定星期/時間窗口跑」的週期性 cron 任務,遇到需要提前執行的事件
# (例:content_inventory_watchdog 偵測存貨低於門檻,不必等到下次排程窗口)時,由觸發方
# `touch` 這個檔案,下一次 cron tick 內該任務就會偵測到並提前跑一次;跑完消耗掉 marker,
# 不會重複觸發。呼叫端仍應保留自己既有的每日鎖(如 DONE 檔案)防同一天被跑兩次。
cron_consume_force_marker() {
  local marker="$1"
  [ -f "$marker" ] || return 1
  rm -f "$marker"
  return 0
}

# cron_cooldown_ok STATE_FILE MIN_DAYS  節流用:STATE_FILE 記錄「上次通過的時間戳(epoch
# 秒數)」。距離上次通過 >= MIN_DAYS 天(或從未通過過)才 return 0 並把現在時間寫進
# STATE_FILE(視為這次也通過、重新起算冷卻);冷卻中則 return 1,不更新檔案。
# 用途:event-driven 提前觸發(如 cron_consume_force_marker)若觸發條件連續多天存在
# (例:存貨持續低迷,補產批次連續被驗證者打回),沒有這層節流會導致每天都真的重跑一次
# 要花錢的操作,而不是原本「一週一次」的節奏——這裡把「觸發條件是否存在」跟「多久可以
# 再真的動手一次」拆開兩層判斷。壞掉/非數字的 STATE_FILE 內容視為「從未通過過」,不可讓
# 髒資料卡死節流。
cron_cooldown_ok() {
  local state_file="$1" min_days="$2" now last days_since
  now=$(date +%s)
  last=$(cat "$state_file" 2>/dev/null || echo 0)
  case "$last" in (''|*[!0-9]*) last=0 ;; esac
  if [ "$last" -gt 0 ]; then
    days_since=$(( (now - last) / 86400 ))
    [ "$days_since" -ge "$min_days" ] || return 1
  fi
  echo "$now" > "$state_file"
  return 0
}

# cron_abort_if_dirty  若 repo 已有 tracked 未 commit 修改（不含 untracked ??），
# 直接讓呼叫腳本 exit 0（靜默略過整輪）。給任何後面會做 `git checkout -- .` /
# `git reset --hard` 這類整樹操作的腳本在動手前守門用 — 保證流程走到那一步時，
# 樹在腳本自己開始改動之前就是乾淨的，後續的 revert 只會碰到腳本自己造成的變動，
# 不會誤傷別人的 WIP。呼叫點必須在任何 git 操作之前。
# ⚠️ 2026-07-18 起新 runner 優先用 cron_abort_if_dirty_scoped(見下)——blanket 版把
# 「別視窗任何無關檔髒」也當讓路條件,實測讓 site_scan cron 連續 13 天餓死(intel ledger
# 檔每日髒 ~13h,daily-cycle 髒齡又低於 dirty_tree_watch 20h 門檻=零告警)。本函式保留
# 給「後續操作真的是整樹級、無法宣告 scope」的腳本。
cron_abort_if_dirty() {
  if ( cd "$CRON_LIB_REPO" && git status --porcelain 2>/dev/null | grep -qv '^??' ); then
    echo "[cron_abort_if_dirty] repo 有未 commit 修改(可能是別視窗 WIP)，本輪略過保護"
    exit 0
  fi
}

# cron_dirty_tracked_files  列出 tracked 且有未 commit 修改(不含 untracked ??)的路徑,
# 一行一檔。porcelain -z --no-renames:NUL 分隔避免特殊字元被 C-style quoting 包裹,
# rename 退化為 D+A 單 token(雙 token 格式曾在 dirty_tree_watch 吞掉下一筆真髒檔,
# 見該檔 docstring)。已知限制:檔名含換行會破壞行輸出(病態案例,tracked 檔無此慣例)。
cron_dirty_tracked_files() {
  ( cd "$CRON_LIB_REPO" || exit 0
    git status --porcelain -z --no-renames 2>/dev/null |
      while IFS= read -r -d '' entry; do
        [ "${#entry}" -lt 4 ] && continue
        [ "${entry:0:2}" = "??" ] && continue
        printf '%s\n' "${entry:3}"
      done )
}

# _cron_tw_today  台灣日期(YYYY-MM-DD)。CRON_FAKE_TODAY 僅供自測注入,生產不設。
_cron_tw_today() { echo "${CRON_FAKE_TODAY:-$(TZ=Asia/Taipei date +%F)}"; }

# 餓死 streak 帳:state 檔一行「streak last_date alerted」。連續(以「不同日期的讓路
# 次數」計,對週頻 runner 也成立)達門檻(預設 2)推 admin 一次(alerted 旗標防重複),
# 成功通過守門即清檔。告警管道可用 CRON_NOTIFY_CMD 覆寫(自測 stub 用)。
_cron_dirty_starve_state_dir() { echo "${CRON_STARVE_STATE_DIR:-$HOME/.marketdaily-fallback/state}"; }

_cron_dirty_starve_mark() {
  local name="$1" files="$2" today streak last alerted dir f
  today=$(_cron_tw_today)
  dir=$(_cron_dirty_starve_state_dir); mkdir -p "$dir"
  f="$dir/dirty_starve_${name}"
  read -r streak last alerted 2>/dev/null < "$f" || { streak=0; last=""; alerted=0; }
  case "$streak" in (''|*[!0-9]*) streak=0 ;; esac
  [ "$last" = "$today" ] && return 0   # 同日多 tick 只計一次
  streak=$((streak + 1)); [ "$streak" -eq 1 ] && alerted=0
  local threshold="${CRON_STARVE_ALERT_AFTER:-2}"
  if [ "$streak" -ge "$threshold" ] && [ "${alerted:-0}" != 1 ]; then
    local msg="🟡 [winrig] cron『${name}』已連續 ${streak} 個班次因 scope 內未 commit 修改讓路(檔:${files})。若是長壽 WIP 請儘快 commit,若是孤兒 cron 輸出檔=缺 persist owner。"
    if [ -n "${CRON_NOTIFY_CMD:-}" ]; then
      $CRON_NOTIFY_CMD "$msg" >/dev/null 2>&1 || true
    else
      MD_REPO="$CRON_LIB_REPO" "$CRON_LIB_REPO/.venv/bin/python" \
        "$HOME/.marketdaily-fallback/notify_admin.py" "$msg" >/dev/null 2>&1 || true
    fi
    alerted=1
  fi
  echo "$streak $today $alerted" > "$f"
}

_cron_dirty_starve_clear() {
  rm -f "$(_cron_dirty_starve_state_dir)/dirty_starve_${1}" 2>/dev/null || true
}

# cron_abort_if_dirty_scoped NAME SCOPE...  path-scoped 版守門(2026-07-18,根治
# 「別視窗無關 WIP 餓死整條 cron 生態鏈」)。dirty tracked 檔 ∩ SCOPE ≠ ∅ 才讓路
# (exit 0+餓死 streak 記帳);scope 外髒檔只記 log 不擋(判準抄 git_safe_push 的
# overlap 檢查)。SCOPE 是目錄(前綴按路徑段匹配,docs 不會誤吃 docs2/)或單檔精確匹配。
# ⚠️ 使用前提(不變量,違反=死線 3b 風險):呼叫端後續【所有】寫檔/git add/commit/
# revert/deploy 都只碰 SCOPE 內路徑;wrangler pages deploy docs 上傳磁碟現狀,所以
# 有 deploy 的 runner SCOPE 必含 docs/。做不到就用 blanket 版 cron_abort_if_dirty。
# 呼叫點放在 cron_daily_lock【之前】:讓路不消耗當日鎖,同日樹變乾淨後續 tick 可重試。
cron_abort_if_dirty_scoped() {
  local name="$1"; shift
  local f s hit blocked="" ignored=""
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    hit=0
    for s in "$@"; do
      s="${s%/}"
      if [ "$f" = "$s" ] || [[ "$f" == "$s"/* ]]; then hit=1; break; fi
    done
    if [ "$hit" = 1 ]; then blocked="${blocked}${f} "; else ignored="${ignored}${f} "; fi
  done < <(cron_dirty_tracked_files)
  if [ -n "$blocked" ]; then
    echo "[cron_abort_if_dirty_scoped:$name] scope 內有未 commit 修改(可能是別視窗 WIP),本輪讓路: ${blocked}"
    _cron_dirty_starve_mark "$name" "$blocked"
    exit 0
  fi
  [ -n "$ignored" ] && echo "[cron_abort_if_dirty_scoped:$name] scope 外髒檔(與本 runner 無關,續行): ${ignored}"
  _cron_dirty_starve_clear "$name"
}

# ── site_scan fix 相位專用:WIP snapshot / targeted revert(取代整樹 git checkout -- .)──
# cron_wip_snapshot SNAP_DIR  把「現在」的 dirty tracked 檔逐一拷貝到 SNAP_DIR(保留相對
# 路徑),並寫 manifest(SNAP_DIR/.manifest,一行一檔)。之後 cron_wip_restore_tampered 用
# manifest+bytes 判斷這批 pre-existing WIP 檔有沒有被中途動到,有就還原 snapshot 原 bytes
# (=忠實還原別視窗 WIP 當時的內容,不是還原 HEAD)。
cron_wip_snapshot() {
  local snap="$1" f
  rm -rf "$snap"; mkdir -p "$snap"
  : > "$snap/.manifest"
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    printf '%s\n' "$f" >> "$snap/.manifest"
    if [ -e "$CRON_LIB_REPO/$f" ]; then
      mkdir -p "$snap/files/$(dirname "$f")"
      cp -p "$CRON_LIB_REPO/$f" "$snap/files/$f"
    fi
  done < <(cron_dirty_tracked_files)
}

# cron_wip_restore_tampered SNAP_DIR  對 manifest 裡每個檔:bytes 與 snapshot 不同(或被
# 刪)→ 還原 snapshot;原本就不存在磁碟(D 狀態)而現在被重建 → 刪回。stdout 印被動過的
# 檔清單(空=無人動)。
cron_wip_restore_tampered() {
  local snap="$1" f tampered=""
  [ -f "$snap/.manifest" ] || return 0
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    if [ -f "$snap/files/$f" ]; then
      if ! cmp -s "$snap/files/$f" "$CRON_LIB_REPO/$f" 2>/dev/null; then
        mkdir -p "$CRON_LIB_REPO/$(dirname "$f")"
        cp -p "$snap/files/$f" "$CRON_LIB_REPO/$f"
        tampered="${tampered}${f} "
      fi
    else
      # snapshot 時是「已刪除」狀態:現在若被重建,刪回維持原 WIP 狀態
      if [ -e "$CRON_LIB_REPO/$f" ]; then
        rm -f "$CRON_LIB_REPO/$f"
        tampered="${tampered}${f} "
      fi
    fi
  done < "$snap/.manifest"
  [ -n "$tampered" ] && echo "$tampered"
  return 0
}

# cron_revert_files FILE...  逐檔 git checkout(還原到 index),絕不整樹。給「本輪自己
# 新造成的變動」用;pre-existing WIP 檔走 cron_wip_restore_tampered,不可混用。
cron_revert_files() {
  local f
  for f in "$@"; do
    [ -n "$f" ] || continue
    git -C "$CRON_LIB_REPO" checkout -- "$f" 2>/dev/null || true
  done
}

# cron_privacy_deploy_guard  部署 docs/ 前的隱私斷路器(2026-07-18,robots /output/ 開放收錄後
# 唯一的 crawl 屏障已拆)。wrangler pages deploy 上傳磁碟現狀(.gitignore 只擋 git 不擋部署),
# docs/output/ 出現任何 *_personal_* 檔(訂閱者持股個資)= 部署即公開可爬,必須擋死本輪部署
# 並告警,絕不靜默跳過。所有執行 `wrangler pages deploy docs` 的 runner 在部署前呼叫:
#   cron_privacy_deploy_guard || exit 1
# find 涵蓋子目錄與無副檔名變體(比單層 glob 寬);目錄不存在=乾淨放行。
cron_privacy_deploy_guard() {
  local _found
  _found=$(find "$CRON_LIB_REPO/docs/output" -name '*_personal_*' -print -quit 2>/dev/null)
  if [ -n "$_found" ]; then
    MD_REPO="$CRON_LIB_REPO" "${PY:-$CRON_LIB_REPO/.venv/bin/python}" \
      "$HOME/.marketdaily-fallback/notify_admin.py" \
      "🔴 [winrig] docs/output/ 發現 *_personal_* 檔(訂閱者隱私),已擋死本輪 docs 部署,需人工清除:$_found" >/dev/null 2>&1 || true
    echo "[cron_privacy_deploy_guard] ABORT: personal file in docs/output/: $_found"
    return 1
  fi
  return 0
}
