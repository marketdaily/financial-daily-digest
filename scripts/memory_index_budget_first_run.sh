#!/bin/bash
# 一次性首班驗收(鐵則 feedback_first_run_acceptance:上線後第一次排程執行要自己驗+PASS/FAIL都推)
STAMP="$HOME/.marketdaily-fallback/.memory_index_budget_accepted"
[ -f "$STAMP" ] && exit 0
ST="$HOME/.marketdaily-fallback/.memory_index_budget.json"
PY="$HOME/Delvin-agent/.venv/bin/python"
TODAY=$(date +%F)
if [ -f "$ST" ] && grep -q "\"checked\": \"$TODAY\"" "$ST"; then
  CH=$(grep -o '"chars": [0-9]*' "$ST" | head -1 | tr -d '"chars: ')
  MSG="✅ 首班驗收 PASS:記憶索引預算守衛 09:25 排程已實跑(今日 chars=$CH,狀態檔已更新)"
else
  MSG="🔴 首班驗收 FAIL:記憶索引預算守衛的 09:25 排程沒跑到(狀態檔非今日)——查 crontab 與 logs/memory_index_budget.log"
fi
"$PY" "$HOME/.marketdaily-fallback/notify_admin.py" "$MSG" && touch "$STAMP"
