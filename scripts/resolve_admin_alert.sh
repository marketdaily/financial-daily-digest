#!/usr/bin/env bash
# 標記 admin 告警已解決(CLAUDE.md 慣例:修完曾推播告警的事故必打,Delvin 後台才知道解了)。
# 用法: resolve_admin_alert.sh "<告警內容子字串>" "<一句怎麼解的>"
# token 在 winrig ~/Delvin-agent/.env(Mac 的是舊值,Mac session 經 winrig MCP 打)。
set -euo pipefail
DIR="$(cd "$(dirname "$0")/.." && pwd)"
TOK="${MARKETDAILY_ALERT_TOKEN:-$(grep -h '^MARKETDAILY_ALERT_TOKEN=' "$DIR/.env" | head -1 | cut -d= -f2- | tr -d '"\r')}"
RESP=$(curl -s -X POST https://marketdaily-alert-worker.delvin-12345678.workers.dev/internal/admin-events-resolve \
  -H "Authorization: Bearer $TOK" -H "Content-Type: application/json" \
  -d "$(python3 -c 'import json,sys;print(json.dumps({"match":sys.argv[1],"note":sys.argv[2] if len(sys.argv)>2 else ""}))' "$1" "${2:-}")")
echo "$RESP"
# 2026-08-10:原本無論結果都 exit 0 —— not_found 時會靜默無作為,
# 未來 session 不看輸出就以為標記成功(CLAUDE.md 的「修完必打」workflow 等於沒執行)。
# 已知 not_found 成因:①關鍵字打錯 ②該則已被標為 resolved(含 info 自動歸檔)
# ③被 admin_events 的 200 則滾動上限擠掉(worker 無讀取端點,無法事後查證)。
# worker 成功時回的是**被更新的那筆事件本身**(含 "resolved": <epoch ms>),不是 {"ok":true}
# ⇒ 舊版每一次「成功」都掉進最後的 fallback 印「標記未確認生效」。守衛對自己的成功喊失敗,
# 用的人只會學會不信它(2026-08-12 標記 credential_watch 誤報時發現)。
if printf '%s' "$RESP" | grep -Eq '"resolved"[[:space:]]*:[[:space:]]*[0-9]+'; then
  exit 0
fi
case "$RESP" in
  *'"ok":true'*) exit 0 ;;
  *not_found*)
    echo "⚠️ 沒有匹配到未解決的告警——這次標記【沒有生效】。" >&2
    echo "   查:關鍵字是否為告警原文子字串(cron 類的標題是『winrig cron『<job>』失敗』);" >&2
    echo "   或該則已滾出 admin_events 的 200 則上限(超過數天前的告警常如此)。" >&2
    exit 3 ;;
  *) echo "⚠️ resolve 回應非預期,標記未確認生效。" >&2; exit 4 ;;
esac
