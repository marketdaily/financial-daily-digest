#!/usr/bin/env bash
# SessionStart hook:把跨視窗的近況灌進新 session 的上下文。
# 目的:用戶常同時開多個 Claude 視窗,新視窗一開就要知道別的視窗剛做了什麼,
# 用戶一提「那個」就能接上,不用再問是哪一個。
set -euo pipefail
REPO="/Users/delvin/Downloads/Delvin agent"
cd "$REPO" 2>/dev/null || exit 0

echo "=== 跨視窗近況(SessionStart 自動注入) ==="

echo "--- 最近 8 筆 git commit ---"
git log -8 --format="%h %cd %s" --date=format:"%m/%d %H:%M" 2>/dev/null || true

UNCOMMITTED="$(git status --short 2>/dev/null | grep -vE '^\?\?' || true)"
if [ -n "$UNCOMMITTED" ]; then
  echo "--- ⚠️ 有未 commit 的改動(可能是另一個視窗正在進行,動它之前先確認) ---"
  echo "$UNCOMMITTED"
fi

if [ -f "$REPO/WORKLOG.md" ]; then
  echo "--- WORKLOG.md 最近 25 行(各視窗開工/收工紀錄) ---"
  tail -n 25 "$REPO/WORKLOG.md" 2>/dev/null || true
fi

echo "=== 規則:做非小事先在 WORKLOG.md 寫一條(日期+在做什麼);改完立刻 commit,別留 working tree 被別的視窗洗掉 ==="
exit 0
