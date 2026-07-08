#!/usr/bin/env bash
# 每日日報短影音生成核心:extract → render → make_post(驗證+上傳+post json)。
# 窗口/每日鎖/通知由呼叫端 runner 負責(winrig: ~/.marketdaily-fallback/video_brief_runner.sh)。
# 失敗以 exit code 回報;stdout/stderr 由呼叫端收。
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"
PY="$REPO/.venv/bin/python"
[ -x "$PY" ] || PY=python3

git pull --rebase --autostash --quiet 2>/dev/null || true
set -a; source .env 2>/dev/null || true; set +a

"$PY" video_brief/extract.py   || exit 10
"$PY" video_brief/render.py    || exit 11
"$PY" video_brief/make_post.py || exit 12
echo "run_daily done"
