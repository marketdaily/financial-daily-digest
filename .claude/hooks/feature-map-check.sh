#!/usr/bin/env bash
# Stop hook:這次 session 動過 docs/ 就對帳 FEATURE_MAP.md。
# 只在真的動過前端時出聲,沒動過完全靜默(不製造噪音)。
cd "${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null)}" || exit 0
git diff --name-only HEAD -- docs/ 2>/dev/null | grep -q . || exit 0
out=$(python3 scripts/feature_map_lint.py 2>&1)
if [ $? -ne 0 ]; then
  echo "⚠️ 這次動過 docs/,但 FEATURE_MAP.md 與程式碼對不上——補完再收工:"
  echo "$out" | tail -20
fi
exit 0
