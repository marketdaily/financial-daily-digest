#!/bin/bash
# 【版控真源;實際部署在 Mac ~/.mac-guard/winrig_tunnel_watch.sh,由 launchd
#   com.delvin.winrig-tunnel-watch(StartInterval 600)執行。改這裡要同步 scp 回 Mac。】
# winrig tunnel / WSL 守衛(Mac 端,2026-07-30 Delvin 核可,已進 allowlist)。
#
# 為什麼這支必須在 Mac(唯一破例的理由):winrig 的 cloudflared 跑在 WSL 裡,
# WSL 假死時 tunnel 一起死,winrig 自己的 deadman 也看不到(它靠 sync 新鮮度,要 30 分鐘後才可能吭聲)。
# 2026-07-30 17:33 就是這樣:MCP 全掛(Cloudflare 1033),18:00 的 deadman 還回報「一切正常」。
# 唯一在 winrig 之外、能從外面看見它的機器就是 Mac。
#
# 做兩件事:
#   ① 探 tunnel(兩次,間隔 45s,避免瞬斷誤報)
#   ② 掛了就分辨三種病因,能自己治的就治:
#      主機不可達(斷電/離線)          → 只告警(治不了)
#      WSL 假死(host 通、wsl 指令 timeout)→ 安全窗口內自動 `wsl --shutdown`,cron/tunnel 會自己回來
#      WSL 活著但 tunnel 不通           → 只告警(cloudflared 死法未知,不亂重啟)
#
# 安全閘:日報班次窗口(TW 06:00-07:35 / 19:00-20:45)不自動重啟,只告警;自動修復 3 小時內只做一次。
# 自包含:token 讀 ~/.mac-guard/.alert_token(launchd 下讀不到 ~/Downloads,TCC 會擋)。
# 測試注入:WT_FAKE_PROBE / WT_FAKE_SSH / WT_FAKE_WSL / WT_FAKE_TW_HHMM / WT_DRY_RUN=1(勿在 launchd 帶)
set -u

GUARD_DIR="$HOME/.mac-guard"
STATE_DIR="$GUARD_DIR/state"
LOG="$GUARD_DIR/tunnel_watch.log"
WORKER="https://marketdaily-alert-worker.delvin-12345678.workers.dev"
TUNNEL_URL="${WT_TUNNEL_URL:-https://wr-80ba1a.marketdaily.ai/}"
SSH_HOST="winrig"
HEAL_LEDGER="$STATE_DIR/tunnel_heal_ledger.tsv"
ALERT_STATE="$STATE_DIR/tunnel_last_alert"
HEAL_COOLDOWN_SEC=10800     # 3h
ALERT_DEDUP_SEC=7200        # 同一種病因 2h 內不重複推
mkdir -p "$STATE_DIR"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "$LOG"; }

# ── tunnel 健康:404 也算健康(tunnel 通、origin 沒有 / 路由);5xx 或 000(連不上)=掛 ──
probe_tunnel() {
  if [ -n "${WT_FAKE_PROBE:-}" ]; then echo "$WT_FAKE_PROBE"; return; fi
  curl -s -o /dev/null -w '%{http_code}' --max-time 12 "$TUNNEL_URL" 2>/dev/null || echo 000
}
tunnel_ok() {  # $1=http code
  case "$1" in 000|5??) return 1 ;; *) return 0 ;; esac
}

host_reachable() {
  [ -n "${WT_FAKE_SSH:-}" ] && return "$WT_FAKE_SSH"
  ssh -o BatchMode=yes -o ConnectTimeout=8 -o StrictHostKeyChecking=no "$SSH_HOST" "cmd /c exit 0" >/dev/null 2>&1
}
wsl_alive() {
  [ -n "${WT_FAKE_WSL:-}" ] && return "$WT_FAKE_WSL"
  # WSL 假死時 wsl.exe 會卡住(0x8007274c),所以要有硬 timeout;ssh 的 ConnectTimeout 管不到已連上之後
  ssh -o BatchMode=yes -o ConnectTimeout=8 "$SSH_HOST" \
      "wsl -d Ubuntu -u userdelvin -- /bin/true" >/dev/null 2>&1 &
  local pid=$! i=0
  while kill -0 "$pid" 2>/dev/null; do
    i=$((i + 1)); [ "$i" -gt 40 ] && { kill -9 "$pid" 2>/dev/null; wait "$pid" 2>/dev/null; return 1; }
    sleep 1
  done
  wait "$pid"
}

tw_hhmm() { [ -n "${WT_FAKE_TW_HHMM:-}" ] && { echo "$WT_FAKE_TW_HHMM"; return; }; TZ=Asia/Taipei date +%H%M; }
in_digest_window() {           # 日報生成/寄出前後不動它
  local t; t=$(tw_hhmm); t=$((10#$t))
  { [ "$t" -ge 600 ]  && [ "$t" -le 735 ];  } && return 0
  { [ "$t" -ge 1900 ] && [ "$t" -le 2045 ]; } && return 0
  return 1
}
heal_cooldown_ok() {
  local last; last=$(tail -1 "$HEAL_LEDGER" 2>/dev/null | cut -f1)
  [ -n "${last:-}" ] || return 0
  [ $(( $(date +%s) - last )) -ge "$HEAL_COOLDOWN_SEC" ]
}

push_admin() {                 # $1=指紋(去重用) $2=訊息
  local fp="$1" msg="$2" last_fp last_ts
  last_fp=$(cut -f2 "$ALERT_STATE" 2>/dev/null); last_ts=$(cut -f1 "$ALERT_STATE" 2>/dev/null)
  if [ "${last_fp:-}" = "$fp" ] && [ -n "${last_ts:-}" ] \
     && [ $(( $(date +%s) - last_ts )) -lt "$ALERT_DEDUP_SEC" ]; then
    log "⏸ 同指紋($fp)仍在冷卻期,不重複推播"; return 0
  fi
  if [ "${WT_DRY_RUN:-0}" = "1" ]; then log "DRY_RUN 推播:[$fp] $(echo "$msg" | head -1)"; return 0; fi
  local token body http
  token=$(cat "$GUARD_DIR/.alert_token" 2>/dev/null)
  [ -n "$token" ] || { log "❌ 推播失敗:.alert_token 不存在"; return 1; }
  body=$(printf '%s' "$msg" | /usr/bin/python3 -c 'import json,sys; print(json.dumps({"message": sys.stdin.read()[:4900]}))')
  http=$(curl -sS -o /dev/null -w '%{http_code}' -X POST "$WORKER/internal/admin-line-push" \
        -H "Content-Type: application/json" -H "Authorization: Bearer $token" \
        -A "mac-guard-tunnel-watch/1.0" --data "$body" --max-time 20 2>>"$LOG")
  log "推播 [$fp] status=$http"
  [ "$http" = "200" ] && printf '%s\t%s\n' "$(date +%s)" "$fp" > "$ALERT_STATE"
  [ "$http" = "200" ]
}

# ── 主流程 ──
code=$(probe_tunnel)
if tunnel_ok "$code"; then
  log "OK tunnel=$code"
  tail -n 300 "$LOG" > "$LOG.tmp" 2>/dev/null && mv "$LOG.tmp" "$LOG"
  exit 0
fi
log "⚠️ tunnel 第一次探測失敗 code=$code,45s 後複驗"
[ "${WT_DRY_RUN:-0}" = "1" ] || sleep 45
code2=$(probe_tunnel)
if tunnel_ok "$code2"; then log "✅ 瞬斷,複驗通過 code=$code2"; exit 0; fi
log "❌ tunnel 確認不通(${code}/${code2}),開始分辨病因"

if ! host_reachable; then
  push_admin "host_down" "🔴 winrig 主機不可達(Mac 端守衛)
tunnel $TUNNEL_URL 兩次失敗(${code}/${code2}),SSH 也連不上。
可能:斷電/關機/Tailscale 掉線。winrig 上的 cron、日報、大腦同步全停。
處理:看電源與網路;主機回來後 cron 會自己接上。"
  exit 1
fi

if wsl_alive; then
  cf=$(ssh -o BatchMode=yes -o ConnectTimeout=8 "$SSH_HOST" \
       "wsl -d Ubuntu -u userdelvin -- pgrep -f 'winrig-remote/config.yml'" 2>/dev/null | tr -d '\r')
  push_admin "tunnel_only" "🟠 winrig tunnel 不通但 WSL 活著(Mac 端守衛)
tunnel $TUNNEL_URL 兩次失敗(${code}/${code2});SSH+WSL 指令都正常。
winrig-remote cloudflared pid: ${cf:-（沒找到=進程死了）}
研判:cloudflared 本身死掉或 Cloudflare 端異常,不是 WSL 假死——沒有自動重啟(死法未知,不亂動)。
處理:winrig 上重跑 cloudflared(winrig-remote/config.yml);MCP 通道在此之前不可用。"
  exit 1
fi

# WSL 假死:host 通、wsl 指令卡住
if in_digest_window; then
  push_admin "wsl_hang_gated" "🟠 winrig WSL 假死(Mac 端守衛)——在日報班次窗口內,**沒有**自動重啟
tunnel 兩次失敗(${code}/${code2});SSH 通但 wsl 指令 timeout(典型 0x8007274c:顯示 Running 卻收不了指令)。
現在是 TW $(tw_hhmm),落在日報生成/寄出窗口,自動 wsl --shutdown 會打斷班次,所以只告警。
要修:ssh winrig \"wsl --shutdown\" → 12 秒後服務會自己全回來(cron/4 支 tunnel/crontab)。"
  exit 1
fi
if ! heal_cooldown_ok; then
  push_admin "wsl_hang_cooldown" "🔴 winrig WSL 又假死(Mac 端守衛)——3 小時內已自動修過一次,這次不再自動重啟
tunnel 兩次失敗(${code}/${code2}),SSH 通但 wsl 指令 timeout。
反覆假死=根因不在「重啟一下」,要人看(WSL/Hyper-V 網路、記憶體、Windows 更新)。
帳本:$HEAL_LEDGER"
  exit 1
fi

log "🔧 判定 WSL 假死且在安全窗口,執行 wsl --shutdown"
if [ "${WT_DRY_RUN:-0}" = "1" ]; then log "DRY_RUN:略過真的重啟"; exit 1; fi
ssh -o BatchMode=yes -o ConnectTimeout=10 "$SSH_HOST" "wsl --shutdown" >/dev/null 2>&1
sleep 15
if wsl_alive && tunnel_ok "$(probe_tunnel)"; then
  printf '%s\t%s\tfixed\n' "$(date +%s)" "$(date '+%F %T')" >> "$HEAL_LEDGER"
  push_admin "wsl_hang_fixed" "✅ winrig WSL 假死已自動修復(Mac 端守衛)
症狀:tunnel 兩次失敗(${code}/${code2})、SSH 通但 wsl 指令 timeout。
處置:wsl --shutdown → WSL 重啟,tunnel 與 cron 已恢復(已複驗)。
無需你動手;若同一天再犯,守衛會改成只告警(3h 冷卻)。"
  log "✅ 自動修復成功"
  exit 0
fi
printf '%s\t%s\tfailed\n' "$(date +%s)" "$(date '+%F %T')" >> "$HEAL_LEDGER"
push_admin "wsl_hang_heal_failed" "🔴 winrig WSL 假死,自動修復失敗(Mac 端守衛)
已跑 wsl --shutdown 但 15 秒後 WSL 或 tunnel 仍不通。
要人看:ssh winrig 後查 wsl -l -v / Windows 事件;必要時重開機。
winrig 上的 cron、日報、大腦同步在此之前全停。"
log "❌ 自動修復失敗"
exit 1
