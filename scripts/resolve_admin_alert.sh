#!/usr/bin/env bash
# 標記 admin 告警已解決(CLAUDE.md 慣例:修完曾推播告警的事故必打,Delvin 後台才知道解了)。
# 用法: resolve_admin_alert.sh "<告警內容子字串>" "<一句怎麼解的>"
# token 在 winrig ~/Delvin-agent/.env(Mac 的是舊值,Mac session 經 winrig MCP 打)。
set -euo pipefail
DIR="$(cd "$(dirname "$0")/.." && pwd)"
TOK="${MARKETDAILY_ALERT_TOKEN:-$(grep -h '^MARKETDAILY_ALERT_TOKEN=' "$DIR/.env" | head -1 | cut -d= -f2- | tr -d '"\r')}"
curl -s -X POST https://marketdaily-alert-worker.delvin-12345678.workers.dev/internal/admin-events-resolve \
  -H "Authorization: Bearer $TOK" -H "Content-Type: application/json" \
  -d "$(python3 -c 'import json,sys;print(json.dumps({"match":sys.argv[1],"note":sys.argv[2] if len(sys.argv)>2 else ""}))' "$1" "${2:-}")"
echo
