#!/bin/bash
# Mac 記憶收件匣拉取(cron 每2h):把 Mac MEMORY_INBOX_MAC.md 的新條目併進本機收件匣(dedup,冪等)。
# 單機主寫制(feedback_memory_single_writer):索引合併由 winrig session/自主機器 groom 做,本腳本只搬運。
MAC="delvin@100.78.136.77"
MACF=".claude/projects/-Users-delvin-Downloads-Delvin-agent/memory/MEMORY_INBOX_MAC.md"
LOCAL="$HOME/.claude/projects/-home-userdelvin-Delvin-agent/memory/MEMORY_INBOX_MAC.md"
TMP=$(mktemp)
ssh -o BatchMode=yes -o ConnectTimeout=10 "$MAC" "cat $MACF" > "$TMP" 2>/dev/null || { rm -f "$TMP"; exit 0; }
[ -s "$TMP" ] || { rm -f "$TMP"; exit 0; }
new=0
while IFS= read -r line; do
  case "$line" in
    "- ["*) grep -qxF -- "$line" "$LOCAL" || { echo "$line" >> "$LOCAL"; new=$((new+1)); } ;;
  esac
done < "$TMP"
rm -f "$TMP"
[ "$new" -gt 0 ] && echo "$(date '+%F %T') 拉入 $new 條 Mac 記憶索引待合併" >> "$HOME/.marketdaily-fallback/memory_inbox_pull.log"
exit 0
