#!/bin/bash
# WSL 記憶體/OOM 守衛 —— 2026-08-05 建立(事故:全部 claude 分頁被一次殺光,連 4 次)
#
# 為什麼要有這支:
#   當次根因是某進程失控吃 11.9GB → WSL kernel global OOM → systemd 的 OOMPolicy=stop
#   連坐停掉 init.scope → 90s 逾時 → SIGKILL 所有互動 session。
#   事後查 journal 只看得到「claude.exe 被殺、rss 11.9GB」,**看不到它的指令列與父進程**,
#   所以無法回答「到底是誰把它拉起來的」。這支的主要價值就在補這個缺口。
#
# 兩件事:
#   ① 事前預警(真正有價值的一半):可用記憶體低於門檻時,把當下 top 進程連 cmdline 一起
#      落盤 + 推播。等到 OOM 真的發生,現場已經沒了,那時再抓只剩進程名。
#   ② 事後偵測:掃 journal 找新的 oom-kill 與 init.scope 連坐擊殺,補推。
#
# ⚠️ 已知限制(誠實寫出來,別讓人以為這支是萬靈丹):
#   init.scope 被 SIGKILL 時這支 cron 自己也會一起死,所以事故「當下」它多半推不出去,
#   要等下一輪 tick 才會補推。事前預警那一半才是能趕在事故前開口的部分。
#
# 退出碼:0=正常 / 1=有異常(cron_run_and_alert 會據此推播 admin,並自帶指紋去重)

set -u

STATE_DIR="${WSL_OOM_STATE_DIR:-$HOME/.marketdaily-fallback/state}"
STATE="$STATE_DIR/wsl_oom_watch.since"
EVIDENCE_DIR="${WSL_OOM_EVIDENCE_DIR:-$HOME/.marketdaily-fallback/state/wsl_oom_evidence}"
# 可用記憶體低於總量這個比例就預警(預設 18%)
WARN_PCT="${WSL_OOM_WARN_PCT:-18}"
mkdir -p "$STATE_DIR" "$EVIDENCE_DIR" 2>/dev/null || true

rc=0
out=""
now_stamp=$(date '+%F %T %z')

# ── 現行犯快照:top RSS 進程 + 完整 cmdline,並標出 interop(.exe)進程 ──
# interop 進程要特別標:它的真身在 Windows 側,Linux 的 OOM killer 殺不死它
# (本次事故四輪 OOM 都選中同一個 PID、rss 一模一樣,就是這個原因),記憶體永遠不會被釋放。
snapshot_procs() {
  ps -eo pid,ppid,rss,etimes,comm,args --sort=-rss 2>/dev/null | head -12 | \
    awk 'NR==1{print "  " $0; next}
         {tag=""; if ($5 ~ /\.exe$/) tag="  ⚠️interop(殺不死,真身在Windows)";
          printf "  %s%s\n", $0, tag}'
}

mem_line() {
  free -m | awk '/^Mem:/{printf "total=%dMB used=%dMB available=%dMB (available %.1f%%)", $2,$3,$7,($7*100/$2)}'
  echo -n " | "
  free -m | awk '/^Swap:/{printf "swap total=%dMB used=%dMB", $2,$3}'
}

# ── ① 事前預警 ──
read -r mem_total mem_avail < <(free -m | awk '/^Mem:/{print $2, $7}')
if [ "${mem_total:-0}" -gt 0 ]; then
  avail_pct=$(( mem_avail * 100 / mem_total ))
  if [ "$avail_pct" -lt "$WARN_PCT" ]; then
    ev="$EVIDENCE_DIR/lowmem_$(date +%Y%m%d_%H%M%S).txt"
    {
      echo "=== WSL 記憶體吃緊快照 $now_stamp ==="
      echo "$(mem_line)"
      echo "--- top RSS 進程(含 cmdline) ---"
      snapshot_procs
    } > "$ev" 2>/dev/null
    out="${out}⚠️ WSL 可用記憶體僅 ${avail_pct}%(門檻 ${WARN_PCT}%)
$(mem_line)
--- 當下最吃記憶體的進程 ---
$(snapshot_procs)
證據已落盤:$ev
"
    rc=1
  fi
fi

# ── ② 事後偵測:自上次檢查點以來的 OOM 與連坐擊殺 ──
since="$(cat "$STATE" 2>/dev/null)"
case "$since" in
  ''|*[!0-9-]*[!0-9:\ +-]*) since="" ;;
esac
[ -n "$since" ] || since="$(date -d '30 min ago' '+%F %T' 2>/dev/null)"

oom_hits=$(journalctl -k --since "$since" --no-pager 2>/dev/null | grep -a 'Out of memory: Killed' | tail -10)
# init.scope 連坐:一個進程 OOM 就把裝著所有互動 session 的 scope 停掉
# (已用 /etc/systemd/system/init.scope.d/ 的 OOMPolicy=continue 修掉,這裡是迴歸哨兵——
#  萬一那份 drop-in 被誰移掉或 systemd 升級洗掉,這行會再度出現而我們會知道)
collateral=$(journalctl --since "$since" --no-pager 2>/dev/null | grep -a 'init.scope: Stopping timed out' | tail -5)

if [ -n "$oom_hits" ]; then
  out="${out}🔴 偵測到 WSL OOM 擊殺(自 ${since} 起):
${oom_hits}
"
  rc=1
fi
if [ -n "$collateral" ]; then
  out="${out}🔴 init.scope 遭連坐停止(=互動 session 被整批 SIGKILL 的那一步)(自 ${since} 起):
${collateral}
⚠️ 這代表 OOMPolicy=continue 的防線沒生效或被移除,請查 /etc/systemd/system/init.scope.d/
"
  rc=1
fi

# 檢查點永遠往前推(事件本身已由 cron_run_and_alert 的指紋去重擋住重複推播),
# 否則同一批舊事件會每輪重推,變成警報疲勞。
date '+%F %T' > "$STATE" 2>/dev/null || true

# ── 防線自身健康度:drop-in 還在不在(沉默的守衛=沒有守衛)──
policy=$(systemctl show init.scope -p OOMPolicy --value 2>/dev/null)
if [ "$policy" != "continue" ]; then
  out="${out}🔴 init.scope OOMPolicy=${policy:-未知}(應為 continue)——連坐防線已失效,一次 OOM 會再次殺光所有分頁。
"
  rc=1
fi

if [ "$rc" -ne 0 ]; then
  echo "=== WSL OOM 守衛 $now_stamp ==="
  printf '%s' "$out"
fi
exit "$rc"
