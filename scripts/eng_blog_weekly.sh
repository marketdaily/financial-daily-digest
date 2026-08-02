#!/usr/bin/env bash
# 技術文章週更提醒(Moonlake 行動清單:每週公開發一篇×3個月)。
# 每週三 10:00 TW 由 winrig crontab 觸發:算當前週次、找下一篇未發布文章、web push 提醒 Delvin。
# 發布後人工登記:echo "<標題或slug>" >> marketing/eng_blog/published.log
set -euo pipefail
DIR="$(cd "$(dirname "$0")/.." && pwd)"
BLOG="$DIR/marketing/eng_blog"
CAL="$BLOG/content_calendar.md"
PUB="$BLOG/published.log"
[ -f "$CAL" ] || exit 0

START=2026-08-03
WEEK=$(( ( $(date +%s) - $(date -d "$START" +%s) ) / 604800 + 1 ))
[ "$WEEK" -ge 1 ] || exit 0
DONE=0; [ -f "$PUB" ] && DONE=$(wc -l < "$PUB")

NEXT_HINT=""
if [ -f "$PUB" ]; then
  NEXT_HINT=$(grep -E '^\|' "$CAL" | grep -vE '^\|[- ]+\||週次|Week' | while IFS= read -r line; do
    title=$(echo "$line" | awk -F'|' '{print $3}' | xargs)
    [ -n "$title" ] && ! grep -qF "$title" "$PUB" && { echo "$title"; break; }
  done | head -1)
else
  NEXT_HINT=$(grep -E '^\|' "$CAL" | grep -vE '^\|[- ]+\||週次|Week' | head -1 | awk -F'|' '{print $3}' | xargs)
fi

MSG="📝 技術文週更 · 第 ${WEEK}/12 週(已發 ${DONE} 篇)
下一篇:${NEXT_HINT:-見內容日曆}
草稿/日曆:marketing/eng_blog/
發布後:echo '標題' >> marketing/eng_blog/published.log"

if [ "$DONE" -lt "$(( WEEK - 1 ))" ]; then
  MSG="⚠️ 技術文週更落後:第 ${WEEK} 週只發了 ${DONE} 篇。
${MSG}"
fi

[ "${DRY_RUN:-0}" = "1" ] && { echo "$MSG"; exit 0; }
TOK=$(grep -h '^MARKETDAILY_ALERT_TOKEN=' "$DIR/.env" | head -1 | cut -d= -f2- | tr -d '"\r')
BODY=$(printf '%s' "$MSG" | python3 -c 'import json,sys; print(json.dumps({"message": sys.stdin.read()[:4900]}))')
curl -sS -o /dev/null -w 'push status=%{http_code}\n' -X POST \
  https://marketdaily-alert-worker.delvin-12345678.workers.dev/internal/admin-line-push \
  -H "Content-Type: application/json" -H "Authorization: Bearer $TOK" \
  -A "eng-blog-weekly/1.0" --data "$BODY" --max-time 20
