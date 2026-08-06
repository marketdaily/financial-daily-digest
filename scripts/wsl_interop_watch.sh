#!/bin/bash
# WSL→Windows exe interop 健康探針(2026-08-06 建立)
#
# 事故背景:巡 sinopac_line(open item #167,LINE 未登入)時發現 line_group_cron.log
# 自 08-05 21:20 起連續多輪印出 `powershell.exe: Invalid argument`——實測任何從這台 WSL
# 呼叫 Windows exe(powershell.exe/cmd.exe/whoami.exe)一律 rc!=0「Invalid argument」,
# 而 WSL 自身(bash/網路/git/claude session)完全正常,是獨立於既有三支守衛之外的故障模式:
#   - wsl_oom_watch.sh 顧記憶體/OOM,探不到 interop 死活
#   - mac_winrig_tunnel_watch.sh 顧 cloudflared tunnel HTTP 健康(WSL 內部網路正常就綠燈,
#     interop 是另一條獨立通道,tunnel 綠燈時 interop 可以照樣是死的)
#   - capability_winrig_wsl_hang_recovery.md 顧的是「wsl -l -v 顯示 Running 但從 Windows
#     呼叫不進 WSL」(0x8007274c),方向相反(Windows→WSL);這支顧的是 WSL→Windows
# 三支現有守衛留下的正是這個盲區,line_group_runner.sh 的螢幕截圖擷取因此靜默死了快一天
# 沒人知道(舊碼零 rc 檢查,見同次修的 line_group_runner.sh)。
#
# 這支只偵測+告警,刻意不自行修復:目前唯一已知復原法是從 Windows/Mac 端 `wsl --shutdown`
# (見 memory capability_winrig_wsl_hang_recovery)。從「裡面」自己重啟等於自砍當下所有
# 互動 session 與其他視窗未存檔的工作,且此腳本執行環境本身沒有到 Windows/Mac 端的
# 觸發管道,不安全也做不到,交由人或 Mac 端 tunnel watch 之後決定時機。
#
# 退出碼:0=interop 正常 / 1=異常(cron_run_and_alert 據此推播,含指紋去重)
set -u
PROBE_EXE="${WSL_INTEROP_PROBE_EXE:-/mnt/c/Windows/System32/cmd.exe}"
TIMEOUT_S="${WSL_INTEROP_TIMEOUT_S:-10}"

if [ ! -e "$PROBE_EXE" ]; then
  echo "探針執行檔不存在:$PROBE_EXE —— 可能是 /mnt/c 掛載路徑改了,非 interop 本身故障,先查這個。"
  exit 1
fi

# 併發鎖(2026-08-06,驗證者分離抓到):cron */5 沒有互斥保護,若探測指令真的卡死
# (`timeout` 到期只送 SIGTERM,子行程若卡在不可中斷狀態不會真的結束——同款根因見
# memory capability_wsl_oom_collateral_kill 的單一失控行程連坐 OOM 事故),沒有鎖
# 就會每 5 分鐘疊加一支新的探測行程,越疊越多。鎖逾時(2×TIMEOUT_S,理論上 timeout+
# 強制 kill 都跑不完才會撞到)視為前一輪異常卡住,直接判故障回報,不強制接管避免
# 兩個探測行程同時打同一個可能有問題的介面。
LOCK="${WSL_INTEROP_LOCK:-$HOME/.marketdaily-fallback/state/.wsl_interop_watch.lock}"
mkdir -p "$(dirname "$LOCK")" 2>/dev/null || true
exec 8>"$LOCK"
if ! flock -n 8; then
  echo "前一輪探測仍在跑(逾時未結束,可能真的卡死,呼應 -k 強制 kill 前就該察覺)——本輪判故障,不重疊執行。"
  exit 1
fi

# -k 5:timeout 到期先送 SIGTERM,5 秒後若還沒死再補 SIGKILL——避免探測指令卡在
# 不可中斷狀態時,`timeout` 本身無限期等待、鎖永遠不釋放。
# ⚠️ 輸出刻意寫進暫存檔而非 `out=$(... 2>&1)` 管道(2026-08-06 自己實測踩到的坑,
# 補在 -k 之後才發現):探測指令若曾衍生出孫行程(真實 Windows exe interop 常見,
# WSL 側的殼行程被 SIGKILL 後,底下的 grandchild 可能被系統重新收養、不會跟著死),
# 這些孫行程若繼承了管道的寫入端,即使 `timeout` 本身已經回傳,command substitution
# 仍會卡住等到「所有持有寫入端的行程都關閉」才返回——`-k` 保證 timeout 自己不卡,
# 保證不了讀取端不卡。改寫檔案:一般檔案的讀取不會被其他行程還開著寫入端擋住,
# `timeout` 一返回就能立刻讀到當下內容,徹底繞開這個 pipe 陷阱。已用「子行程
# trap 掉 SIGTERM、只能被 SIGKILL 殺」的情境重現過:管道版卡滿全部 TIMEOUT_S,
# 檔案版在 -k 生效後正常返回。
TMPOUT="$(mktemp "${TMPDIR:-/tmp}/wsl_interop_watch.XXXXXX")"
trap 'rm -f "$TMPOUT"' EXIT
timeout -k 5 "$TIMEOUT_S" "$PROBE_EXE" /c exit 0 > "$TMPOUT" 2>&1
rc=$?
out="$(cat "$TMPOUT" 2>/dev/null)"

if [ "$rc" -ne 0 ]; then
  echo "WSL→Windows exe interop 異常:$PROBE_EXE /c exit 0 → rc=$rc"
  echo "輸出:${out:-<空,可能是 timeout>}"
  echo "受影響:任何從這台 WSL 呼叫 /mnt/c/Windows 下 exe 的 cron(目前已知:line_group_runner.sh"
  echo "券商喊單截圖、line_watch.sh、seed_agent_browser.sh),以及 notify_admin.py 的桌面 toast 通道"
  echo "(web push 通道走純 python urllib,不受影響,admin 告警本身仍會送達)。"
  echo "已知復原法(只能從 Windows/Mac 端做,WSL 裡面重啟不了自己):"
  echo "  ssh winrig \"wsl --shutdown\"  (Windows 帳號,Tailscale;避開日報班次"
  echo "  TW 06:00-07:35 / 19:00-20:45,見 memory capability_winrig_wsl_hang_recovery.md)"
  exit 1
fi
echo "interop 正常:$PROBE_EXE /c exit 0 → rc=0"
exit 0
