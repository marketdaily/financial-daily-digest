#!/bin/bash
# report-only ruff 快照(backlog P2「工程師體檢④後續」)。
# 只印統計+寫入 dated log,不 exit 非零、不擋任何 commit/deploy。
# 用法: scripts/lint_report.sh   (需先 pip install ruff 或指定 RUFF_BIN)
set -uo pipefail
cd "$(dirname "$0")/.."

RUFF_BIN="${RUFF_BIN:-ruff}"
if ! command -v "$RUFF_BIN" >/dev/null 2>&1; then
    echo "ruff 未安裝,略過(report-only,不視為失敗)。安裝: pip install ruff 或設 RUFF_BIN=/path/to/ruff"
    exit 0
fi

mkdir -p logs/lint
OUT="logs/lint/$(date +%F).txt"
"$RUFF_BIN" check . --statistics > "$OUT" 2>&1
echo "ruff report-only 快照 → $OUT"
tail -5 "$OUT"
exit 0
