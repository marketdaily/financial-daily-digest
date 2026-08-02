#!/usr/bin/env bash
# 一次性 HN 投稿(Moonlake 行動線文章#1 英文版)。成功後寫 done 標記自鎖+推播;cron 排 2026-08-03 21:30 TW。
set -euo pipefail
DIR="$(cd "$(dirname "$0")/.." && pwd)"
MARK="$DIR/marketing/eng_blog/.hn_submitted_council"
[ -f "$MARK" ] && exit 0
U=$(grep -h '^HN_USERNAME=' "$DIR/.env" | head -1 | cut -d= -f2- | tr -d '"\r')
P=$(grep -h '^HN_PASSWORD=' "$DIR/.env" | head -1 | cut -d= -f2- | tr -d '"\r')
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
CJ=$(mktemp)
TITLE="I run a 9-model LLM council to write a financial newsletter. What breaks"
URL="https://marketdaily.ai/blog/eng-llm-council-judge-en-202608"

curl -s -c "$CJ" -A "$UA" -d "acct=$U&pw=$P&goto=news" https://news.ycombinator.com/login -o /dev/null
FNID=$(curl -s -b "$CJ" -A "$UA" https://news.ycombinator.com/submit | grep -o 'name="fnid" value="[^"]*"' | head -1 | cut -d'"' -f4)
[ -n "$FNID" ] || { echo "fnid 取不到(登入失敗?)"; exit 1; }
curl -s -b "$CJ" -A "$UA" -d "fnid=$FNID&fnop=submit-page&title=$(python3 -c "import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1]))" "$TITLE")&url=$URL&text=" https://news.ycombinator.com/r -o /dev/null
sleep 3
ITEM=$(curl -s -A "$UA" "https://news.ycombinator.com/submitted?id=$U" | grep -o 'item?id=[0-9]*' | head -1)
if [ -n "$ITEM" ]; then
  touch "$MARK"
  MSG="🟠 HN 已投稿:$TITLE
https://news.ycombinator.com/$ITEM
(帳號 $U;不刷票,自然流量)"
else
  MSG="⚠️ HN 投稿疑似失敗(submitted 頁查無),需人工看:scripts/hn_submit_once.sh"
fi
TOK=$(grep -h '^MARKETDAILY_ALERT_TOKEN=' "$DIR/.env" | head -1 | cut -d= -f2- | tr -d '"\r')
printf '%s' "$MSG" | python3 -c 'import json,sys; print(json.dumps({"message": sys.stdin.read()[:4900]}))' | \
curl -s -o /dev/null -X POST https://marketdaily-alert-worker.delvin-12345678.workers.dev/internal/admin-line-push \
  -H "Content-Type: application/json" -H "Authorization: Bearer $TOK" -A "hn-submit/1.0" --data @-
rm -f "$CJ"
